{% set _ = salt['omv_utils.register_jinja_filters']() %}
{%- from 'omv/deploy/garage/literal.jinja' import literal %}

{%- set instances = salt['omv_conf.get']('conf.service.garage.instance') %}
{#- Everything the instances need, decided by the plugin's PHP code. #}
{%- set render = salt['cmd.run_all'](['/usr/bin/php', '/usr/share/openmediavault/garage/render-instances.php']) %}
{%- set rendered = render.stdout | load_json if render.retcode == 0 else {'instances': {}, 'orphans': []} %}
{%- set etcdir = '/etc/garage' %}
{%- set nginxd = '/etc/nginx/openmediavault-webgui.d' %}

configure_garage_etc_dir:
  file.directory:
    - name: {{ etcdir }}
    - user: root
    - group: garage
    - mode: '0750'

configure_garage_nginx_dir:
  file.directory:
    - name: {{ nginxd }}
    - user: root
    - group: root
    - mode: '0755'

{% if render.retcode != 0 %}
render_garage:
  test.fail_without_changes:
    - comment: {{ literal(render.stderr) }}
{% else %}
{#- Every shared folder the plugin grants the garage ACL on is recorded
    before the grant, so later applies revoke only the plugin's own ACLs. #}
record_garage_acls:
  file.managed:
    - name: {{ rendered.acls.record }}
    - contents: {{ literal(literal(rendered.acls.granted)) }}
    - makedirs: True
    - user: root
    - group: root
    - mode: '0644'
{% endif %}

{% for instance in instances | selectattr('enable') %}
{% set name = instance.name %}
{%- set result = rendered.instances[name] | default({'error': 'garage@' ~ name ~ ': not rendered'}) %}

{% if 'error' in result %}
render_garage_{{ name }}:
  test.fail_without_changes:
    - comment: {{ literal(result.error) }}
{% else %}
{%- set model = result.model %}

{% if model.dirs | length > 0 %}
configure_garage_dirs_{{ name }}:
  file.directory:
    - names:
{%- for d in model.dirs %}
      - {{ literal(d) }}
{%- endfor %}
    - user: garage
    - group: garage
    - mode: '0700'
{% endif %}

configure_garage_toml_{{ name }}:
  file.managed:
    - name: {{ etcdir }}/{{ name }}.toml
    - source:
      - salt://{{ tpldir }}/files/garage.toml.j2
    - template: jinja
    - context:
        instance: {{ literal(instance) }}
        model: {{ literal(model) }}
    - user: root
    - group: garage
    - mode: '0640'

configure_garage_rpc_secret_{{ name }}:
  file.managed:
    - name: {{ etcdir }}/{{ name }}.rpc_secret
    - contents: {{ literal(instance.rpcsecret) }}
    - user: garage
    - group: garage
    - mode: '0600'

configure_garage_drop_in_{{ name }}:
  file.managed:
    - name: /etc/systemd/system/garage@{{ name }}.service.d/override.conf
    - makedirs: True
    - source:
      - salt://{{ tpldir }}/files/instance-override.conf.j2
    - template: jinja
    - context:
        instance: {{ literal(instance) }}
        paths: {{ literal(model.shares | list) }}
        drain: {{ literal(model.drain) }}
    - user: root
    - group: root
    - mode: '0644'

configure_garage_acl_{{ name }}:
  cmd.run:
    - names:
{%- for path, perms in model.shares.items() %}
      - {{ literal('setfacl -m u:garage:' ~ perms ~ ' ' ~ path | quote) }}
{%- endfor %}
    - unless:
{%- for path, perms in model.shares.items() %}
      - {{ literal('getfacl -p ' ~ path | quote ~ " | grep -q '^user:garage:" ~ perms ~ "'") }}
{%- endfor %}
    - require:
      - file: record_garage_acls

garage_systemd_reload_{{ name }}:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: configure_garage_drop_in_{{ name }}

start_garage_{{ name }}:
  service.running:
    - name: garage@{{ name }}
    - enable: True
    - watch:
      - file: configure_garage_toml_{{ name }}
      - file: configure_garage_rpc_secret_{{ name }}
      - file: configure_garage_drop_in_{{ name }}
    - require:
      - cmd: garage_systemd_reload_{{ name }}
      - cmd: configure_garage_acl_{{ name }}

bootstrap_garage_{{ name }}:
  cmd.run:
    - name: {{ literal(['/usr/bin/php', '/usr/share/openmediavault/garage/bootstrap-instance.php', name, model.layout_capacity | string] | map('quote') | join(' ')) }}
    - require:
      - service: start_garage_{{ name }}

{% if model.drain %}
rebalance_garage_{{ name }}:
  cmd.run:
    - name: {{ literal(['/usr/share/openmediavault/garage/start-rebalance.sh', name] | map('quote') | join(' ')) }}
    - require:
      - service: start_garage_{{ name }}
{% endif %}

{% if instance.webuienable %}
{%- set webuienv = etcdir ~ '/' ~ name ~ '.webui.env' %}

configure_garage_webui_env_{{ name }}:
  file.managed:
    - name: {{ webuienv }}
    - source:
      - salt://{{ tpldir }}/files/webui.env.j2
    - template: jinja
    - context:
        instance: {{ literal(instance) }}
        ports: {{ literal(model.ports) }}
        passwordhash: {{ literal(salt['cmd.run'](['/usr/bin/php', '/usr/share/openmediavault/garage/webui-password-hash.php', webuienv], stdin=instance.webuipassword)) }}
    - user: root
    - group: garage
    - mode: '0640'

start_garage_webui_{{ name }}:
  service.running:
    - name: omv-garage-webui@{{ name }}
    - enable: True
    - watch:
      - file: configure_garage_webui_env_{{ name }}
    - require:
      - service: start_garage_{{ name }}

configure_garage_webui_nginx_{{ name }}:
  file.managed:
    - name: {{ nginxd }}/garage-webui-{{ name }}.conf
    - source:
      - salt://{{ tpldir }}/files/nginx-webui.conf.j2
    - template: jinja
    - context:
        instance: {{ literal(instance) }}
        ports: {{ literal(model.ports) }}
    - user: root
    - group: root
    - mode: '0644'
    - watch_in:
      - cmd: garage_nginx_reload

{% else %}

stop_garage_webui_{{ name }}:
  service.dead:
    - name: omv-garage-webui@{{ name }}
    - enable: False

purge_garage_webui_nginx_{{ name }}:
  file.absent:
    - name: {{ nginxd }}/garage-webui-{{ name }}.conf
    - watch_in:
      - cmd: garage_nginx_reload

purge_garage_webui_env_{{ name }}:
  file.absent:
    - name: {{ etcdir }}/{{ name }}.webui.env

{% endif %}
{% endif %}

{% endfor %}

{#- Stop and clean up the instances the plugin rendered that were deleted
    or disabled. Their data and garage ACLs stay. The toml goes last: it
    marks the files as the plugin's. #}
{% for name in rendered.orphans %}
purge_orphan_garage_service_{{ name }}:
  service.dead:
    - name: garage@{{ name }}
    - enable: False

purge_orphan_garage_webui_{{ name }}:
  service.dead:
    - name: omv-garage-webui@{{ name }}
    - enable: False

purge_orphan_garage_files_{{ name }}:
  cmd.run:
    - name: |
        rm -f {{ (etcdir ~ '/' ~ name ~ '.rpc_secret') | quote }} {{ (etcdir ~ '/' ~ name ~ '.webui.env') | quote }}
        rm -f {{ (nginxd ~ '/garage-webui-' ~ name ~ '.conf') | quote }}
        rm -rf {{ ('/etc/systemd/system/garage@' ~ name ~ '.service.d') | quote }}
        systemctl daemon-reload
        rm -f {{ (etcdir ~ '/' ~ name ~ '.toml') | quote }}
    - watch_in:
      - cmd: garage_nginx_reload

{% endfor %}

{#- Shared folders the plugin granted that no instance uses lose the garage
    ACL. A drained datastore also loses the marker and the empty hash
    directories garage left in it. #}
{% if render.retcode == 0 and rendered.acls.revoke %}
{% for path in rendered.acls.revoke %}
{%- set revoke -%}
if [ -f {{ (path ~ 'garage-marker') | quote }} ] &&
  [ -z "$(find {{ path | quote }} -type f ! -name garage-marker -print -quit)" ]; then
  find {{ path | quote }} -mindepth 1 -maxdepth 2 -type d -name '[0-9a-f][0-9a-f]' -empty -delete &&
    rm {{ (path ~ 'garage-marker') | quote }}
fi && setfacl -x u:garage {{ path | quote }}
{%- endset %}
revoke_garage_acl_{{ loop.index }}:
  cmd.run:
    - name: {{ literal(revoke) }}
    - onlyif: {{ literal('getfacl -p ' ~ path | quote ~ " | grep -q '^user:garage:'") }}
{% endfor %}

forget_garage_acls:
  file.managed:
    - name: {{ rendered.acls.record }}
    - contents: {{ literal(literal(rendered.acls.kept)) }}
    - require:
{%- for path in rendered.acls.revoke %}
      - cmd: revoke_garage_acl_{{ loop.index }}
{%- endfor %}
{% endif %}

garage_nginx_reload:
  cmd.run:
    - name: nginx -t && systemctl reload nginx
    - onlyif: test -d /run/systemd/system

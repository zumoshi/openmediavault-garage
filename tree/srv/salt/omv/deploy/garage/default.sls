{% set _ = salt['omv_utils.register_jinja_filters']() %}

{%- set service = salt['omv_conf.get']('conf.service.garage') %}
{%- set instances = salt['omv_conf.get']('conf.service.garage.instance') %}
{%- set datastores = salt['omv_conf.get']('conf.service.garage.datastore') %}
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

{#- Collect the enabled instances with their resolved share paths. #}
{%- set enabled = [] %}
{%- for instance in instances %}
{%- if service.enable | to_bool and instance.enable | to_bool %}
{%- set paths = [] %}
{%- set mntpaths = [] %}
{%- if instance.metadatashareuuid | length == 36 %}
{%- set _ = paths.append(salt['omv_conf.get_sharedfolder_path'](instance.metadatashareuuid)) %}
{%- endif %}
{%- if instance.snapshotsshareuuid | length == 36 %}
{%- set _ = paths.append(salt['omv_conf.get_sharedfolder_path'](instance.snapshotsshareuuid)) %}
{%- endif %}
{%- set dslist = [] %}
{%- set ns = namespace(capacitybytes=0) %}
{%- for datastore in datastores %}
{%- if datastore.instanceuuid == instance.uuid %}
{%- set _ = paths.append(salt['omv_conf.get_sharedfolder_path'](datastore.shareuuid)) %}
{%- set _ = dslist.append(datastore) %}
{%- set ns.capacitybytes = ns.capacitybytes + (datastore.capacity | int * 1073741824) %}
{%- endif %}
{%- endfor %}
{%- set _ = enabled.append({
  'instance': instance,
  'paths': paths,
  'dslist': dslist,
  'capacitybytes': ns.capacitybytes
}) %}
{%- endif %}
{%- endfor %}

{% for entry in enabled %}
{% set instance = entry.instance %}
{% set name = instance.name %}

configure_garage_toml_{{ name }}:
  file.managed:
    - name: {{ etcdir }}/{{ name }}.toml
    - source:
      - salt://{{ tpldir }}/files/garage.toml.j2
    - template: jinja
    - context:
        instance: {{ instance | json }}
        dslist: {{ entry.dslist | json }}
    - user: root
    - group: garage
    - mode: '0640'

configure_garage_rpc_secret_{{ name }}:
  file.managed:
    - name: {{ etcdir }}/{{ name }}.rpc_secret
    - contents: {{ instance.rpcsecret | json }}
    - user: root
    - group: garage
    - mode: '0640'

configure_garage_drop_in_{{ name }}:
  file.managed:
    - name: /etc/systemd/system/garage@{{ name }}.service.d/override.conf
    - source:
      - salt://{{ tpldir }}/files/instance-override.conf.j2
    - template: jinja
    - context:
        instance: {{ instance | json }}
        paths: {{ entry.paths | json }}
    - user: root
    - group: root
    - mode: '0644'

configure_garage_acl_{{ name }}:
  cmd.run:
    - names:
{%- for path in entry.paths %}
      - setfacl -m u:garage:rwX {{ path }}
{%- endfor %}
    - unless:
{%- for path in entry.paths %}
      - getfacl -p {{ path }} | grep -q '^user:garage:rw'
{%- endfor %}

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
    - name: /usr/bin/php /usr/share/openmediavault/garage/bootstrap-instance.php {{ name }} {{ entry.capacitybytes }}
    - require:
      - service: start_garage_{{ name }}

{% if instance.webuienable %}

configure_garage_webui_env_{{ name }}:
  file.managed:
    - name: {{ etcdir }}/{{ name }}.webui.env
    - source:
      - salt://{{ tpldir }}/files/webui.env.j2
    - template: jinja
    - context:
        instance: {{ instance | json }}
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
        instance: {{ instance | json }}
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

{% endfor %}

{#- Clean up instances that were deleted from the configuration. #}
{%- set managednames = [] %}
{%- for instance in instances %}
{%- set _ = managednames.append(instance.name) %}
{%- endfor %}
{%- set orphans = [] %}
{%- for tomlpath in salt['file.find'](etcdir, name='*.toml') | sort %}
{%- set oname = salt['file.basename'](tomlpath) | replace('.toml', '') %}
{%- if oname not in managednames %}
{%- set _ = orphans.append(oname) %}
{%- endif %}
{%- endfor %}
{% for name in orphans %}
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
        rm -f {{ etcdir }}/{{ name }}.toml {{ etcdir }}/{{ name }}.rpc_secret {{ etcdir }}/{{ name }}.webui.env
        rm -f {{ nginxd }}/garage-webui-{{ name }}.conf
        rm -rf /etc/systemd/system/garage@{{ name }}.service.d
        systemctl daemon-reload
    - watch_in:
      - cmd: garage_nginx_reload

{% endfor %}

garage_nginx_reload:
  cmd.run:
    - name: nginx -t && systemctl reload nginx
    - onlyif: test -d /run/systemd/system

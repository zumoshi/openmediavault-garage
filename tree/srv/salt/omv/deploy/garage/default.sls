{% set _ = salt['omv_utils.register_jinja_filters']() %}

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
{%- if instance.enable | to_bool %}
{%- set split = instance.storagesplit | to_bool %}
{%- set storpath = salt['omv_conf.get_sharedfolder_path'](instance.storageshareuuid) %}
{%- set storbase = storpath | regex_replace('/$', '') %}
{%- set metapath = '' %}
{%- set metabase = '' %}
{%- if split %}
{%- set metapath = salt['omv_conf.get_sharedfolder_path'](instance.metadatashareuuid) %}
{%- set metabase = metapath | regex_replace('/$', '') %}
{%- endif %}
{%- set storbase = storpath | regex_replace('/$', '') %}
{%- set paths = [storpath] %}
{%- set dirs = [] %}
{%- if split %}
{%- if metapath != storpath %}
{%- set _ = paths.append(metapath) %}
{%- set _ = dirs.append(metabase ~ '/meta') %}
{%- endif %}
{%- else %}
{%- set _ = dirs.extend([storbase ~ '/meta', storbase ~ '/data']) %}
{%- endif %}
{%- if instance.snapshotsshareuuid | length == 36 %}
{%- set _ = paths.append(salt['omv_conf.get_sharedfolder_path'](instance.snapshotsshareuuid)) %}
{%- endif %}
{%- set dslist = [] %}
{%- set datadirs = [] %}
{%- if not split %}
{%- set _ = datadirs.append(storbase ~ '/data') %}
{%- endif %}
{%- set ns = namespace(capacitybytes=0, storfreegib=0) %}
{%- if not split %}
{#- Size the storage dataset from the free space of its shared folder. #}
{%- set dfraw = salt['cmd.run'](['df', '-B1', '--output=avail', storbase]) %}
{%- set dflines = dfraw.strip().split('\n') %}
{%- set dfout = dflines | last | int %}
{%- set ns.storfreegib = ((dfout * 0.9 / 1073741824) | round(0, 'floor') | int) %}
{%- endif %}
{%- for datastore in datastores %}
{%- if datastore.instanceuuid == instance.uuid %}
{%- set ds_path = salt['omv_conf.get_sharedfolder_path'](datastore.shareuuid) %}
{%- set _ = paths.append(ds_path) %}
{%- set _ = dslist.append(datastore) %}
{%- set _ = datadirs.append(ds_path) %}
{%- set ns.capacitybytes = ns.capacitybytes + (datastore.capacity | int * 1073741824) %}
{%- endif %}
{%- endfor %}
{%- set ns.capacitybytes = ns.capacitybytes + ns.storfreegib * 1073741824 %}
{%- if datadirs | length == 0 %}
{%- set _ = datadirs.append(storbase ~ '/data') %}
{%- endif %}
{%- set _ = enabled.append({
  'instance': instance,
  'storpath': storpath,
  'storbase': storbase,
  'metapath': metapath,
  'metabase': metabase,
  'split': split,
  'paths': paths,
  'dirs': dirs,
  'dslist': dslist,
  'datadirs': datadirs,
  'storfreegib': ns.storfreegib,
  'capacitybytes': ns.capacitybytes
}) %}
{%- endif %}
{%- endfor %}

{% for entry in enabled %}
{% set instance = entry.instance %}
{% set name = instance.name %}

{% if entry.dirs | length > 0 %}
configure_garage_dirs_{{ name }}:
  file.directory:
    - names:
{%- for d in entry.dirs %}
      - {{ d | json }}
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
        instance: {{ instance | json }}
        storpath: {{ entry.storpath | json }}
        storbase: {{ entry.storbase | json }}
        metapath: {{ entry.metapath | json }}
        metabase: {{ entry.metabase | json }}
        split: {{ entry.split | to_bool | json }}
        storfreegib: {{ entry.storfreegib | json }}
        dslist: {{ entry.dslist | json }}
    - user: root
    - group: garage
    - mode: '0640'

configure_garage_rpc_secret_{{ name }}:
  file.managed:
    - name: {{ etcdir }}/{{ name }}.rpc_secret
    - contents: {{ instance.rpcsecret | json }}
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
        instance: {{ instance | json }}
        paths: {{ entry.paths | json }}
    - user: root
    - group: root
    - mode: '0644'

configure_garage_acl_{{ name }}:
  cmd.run:
    - names:
{%- for path in entry.paths %}
      - {{ ('setfacl -m u:garage:rwX ' ~ path | quote) | json }}
{%- endfor %}
    - unless:
{%- for path in entry.paths %}
      - {{ ('getfacl -p ' ~ path | quote ~ " | grep -q '^user:garage:rw'") | json }}
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
    - name: {{ (['/usr/bin/php', '/usr/share/openmediavault/garage/bootstrap-instance.php', name, entry.capacitybytes | string] + entry.datadirs) | map('quote') | join(' ') | json }}
    - require:
      - service: start_garage_{{ name }}

{% if instance.webuienable %}
{%- set webuienv = etcdir ~ '/' ~ name ~ '.webui.env' %}

configure_garage_webui_env_{{ name }}:
  file.managed:
    - name: {{ webuienv }}
    - source:
      - salt://{{ tpldir }}/files/webui.env.j2
    - template: jinja
    - context:
        instance: {{ instance | json }}
        passwordhash: {{ salt['cmd.run'](['/usr/bin/php', '/usr/share/openmediavault/garage/webui-password-hash.php', webuienv], stdin=instance.webuipassword) | json }}
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
        rm -f {{ (etcdir ~ '/' ~ name ~ '.toml') | quote }} {{ (etcdir ~ '/' ~ name ~ '.rpc_secret') | quote }} {{ (etcdir ~ '/' ~ name ~ '.webui.env') | quote }}
        rm -f {{ (nginxd ~ '/garage-webui-' ~ name ~ '.conf') | quote }}
        rm -rf {{ ('/etc/systemd/system/garage@' ~ name ~ '.service.d') | quote }}
        systemctl daemon-reload
    - watch_in:
      - cmd: garage_nginx_reload

{% endfor %}

garage_nginx_reload:
  cmd.run:
    - name: nginx -t && systemctl reload nginx
    - onlyif: test -d /run/systemd/system

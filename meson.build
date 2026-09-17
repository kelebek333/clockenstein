project('clockenstein', version : '1.0.0', meson_version : '>= 0.59.0')

prefix = get_option('prefix')
datadir = get_option('datadir')
bindir = get_option('bindir')
clockenstein_dir = join_paths(prefix, datadir, 'clockenstein')
calendar_dir = join_paths(clockenstein_dir, 'calendar')
clocks_dir = join_paths(clockenstein_dir, 'clocks')
daemon_dir = join_paths(clockenstein_dir, 'daemon')
agent_dir = join_paths(clockenstein_dir, 'agent')
sounds_dir = join_paths(clockenstein_dir, 'sounds')
systemd_user_unit_dir = join_paths(prefix, 'lib', 'systemd', 'user')

install_data(
  'calendar/calendar_app.py',
  'calendar/dbus.py',
  'calendar/store.py',
  'calendar/event_dialog.py',
  'calendar/preferences.py',
  'calendar/style.css',
  install_dir: calendar_dir,
)

install_data(
  'clocks/clocks_app.py',
  'clocks/style.css',
  install_dir: clocks_dir,
)

install_data(
  'clockenstein/__init__.py',
  'clockenstein/calendars.py',
  'clockenstein/sync.py',
  'clockenstein/drawing.py',
  'clockenstein/formatting.py',
  'clockenstein/logging.py',
  install_dir: join_paths(prefix, 'lib', 'python3', 'dist-packages', 'clockenstein'),
)
configure_file(
  input: 'clockenstein/alarms.py',
  output: 'alarms.py',
  configuration: {'datadir': join_paths(prefix, datadir)},
  install: true,
  install_dir: join_paths(prefix, 'lib', 'python3', 'dist-packages', 'clockenstein'),
)
install_data('data/notification.oga', install_dir: sounds_dir)

custom_target('clockenstein_daemon_versioned',
  input: 'daemon/daemon.py',
  output: 'daemon.py',
  command: ['sed', 's/__PROJECT_VERSION__/@0@/g'.format(meson.project_version()), '@INPUT@'],
  capture: true,
  install: true,
  install_dir: daemon_dir,
)

custom_target('clockenstein_main_window_versioned',
  input: 'calendar/main_window.py',
  output: 'main_window.py',
  command: ['sed', 's/__PROJECT_VERSION__/@0@/g'.format(meson.project_version()), '@INPUT@'],
  capture: true,
  install: true,
  install_dir: calendar_dir,
)

install_data(
  'agent/agent.py',
  install_dir: agent_dir,
)

install_data(
  'calendar/backends/google.py',
  'calendar/backends/remote.py',
  'calendar/backends/caldav.py',
  install_dir: join_paths(calendar_dir, 'backends'),
)

install_data(
  'calendar/views/__init__.py',
  'calendar/views/colors.py',
  'calendar/views/month_view.py',
  'calendar/views/week_view.py',
  'calendar/views/day_view.py',
  install_dir: join_paths(calendar_dir, 'views'),
)

install_data(
  'calendar/widgets/mini_calendar.py',
  install_dir: join_paths(calendar_dir, 'widgets'),
)

launcher_conf = configuration_data()
launcher_conf.set('calendar_dir', calendar_dir)
launcher_conf.set('clocks_dir', clocks_dir)
launcher_conf.set('daemon_dir', daemon_dir)
launcher_conf.set('agent_dir', agent_dir)
install_data(
  'cli/cli_app.py',
  rename: 'clockenstein-cli',
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

configure_file(
  input: 'data/clockenstein-calendar.in',
  output: 'clockenstein-calendar',
  configuration: launcher_conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

configure_file(
  input: 'data/clockenstein-clocks.in',
  output: 'clockenstein-clocks',
  configuration: launcher_conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

configure_file(
  input: 'data/clockenstein-daemon.in',
  output: 'clockenstein-daemon',
  configuration: launcher_conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

configure_file(
  input: 'data/clockenstein-notification-agent.in',
  output: 'clockenstein-notification-agent',
  configuration: launcher_conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

service_conf = configuration_data()
service_conf.set('bindir', join_paths(prefix, bindir))
configure_file(
  input: 'data/org.x.clockenstein.Calendar.Service.service.in',
  output: 'org.x.clockenstein.Calendar.Service.service',
  configuration: service_conf,
  install: true,
  install_dir: join_paths(get_option('datadir'), 'dbus-1', 'services'),
)

configure_file(
  input: 'data/clockenstein-daemon.service.in',
  output: 'clockenstein-daemon.service',
  configuration: service_conf,
  install: true,
  install_dir: systemd_user_unit_dir,
)

configure_file(
  input: 'data/clockenstein-notification-agent.service.in',
  output: 'clockenstein-notification-agent.service',
  configuration: service_conf,
  install: true,
  install_dir: systemd_user_unit_dir,
)

install_data(
  'data/clockenstein-daemon.desktop.in',
  rename: 'clockenstein-daemon.desktop',
  install_dir: join_paths(get_option('sysconfdir'), 'xdg', 'autostart'),
)

install_data(
  'data/clockenstein-notification-agent.desktop.in',
  rename: 'clockenstein-notification-agent.desktop',
  install_dir: join_paths(get_option('sysconfdir'), 'xdg', 'autostart'),
)

subdir('data')
subdir('po')

python3 = find_program('/usr/bin/python3')
test(
  'unit-tests',
  python3,
  args: ['-m', 'unittest', 'discover', '-s', 'tests', '-v'],
  env: ['PYTHONDONTWRITEBYTECODE=1'],
  workdir: meson.project_source_root(),
)

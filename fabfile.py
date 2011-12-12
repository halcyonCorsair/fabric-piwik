from fabric.api import *
from fabric.colors import green, red, yellow
from fabric.contrib.console import confirm
from fabric.contrib.files import *
import time
from sitedef import setup_site_environment
#from sitedef import setup_hosts

time = time.strftime('%Y%m%d-%H%M')

# TODO: Add support for tagging a release
"""
def tag(branch, tag, stage=''):
  user = local('git config --get user.name', capture=True)
  email = local('git config --get user.email', capture=True)
  tag = "release_%s" % tag
  if (stage != ''):
    tag = "%s_%s" % (stage, tag)
  end
  #local('git tag %s #{revision} -m "Deployed by #{user} <#{email}>"')
  #local('git push origin tag %s' % tag)
"""

def do_release(stage='uat',release_tag='master'):
  env.stage = stage
  setup_site_environment()
  setup_environment()

  print "===> Build release"
  build_release(release_tag)
  print "===> Deploy release archive"
  deploy_release_archive()
  print "===> Deploy release"
  deploy_release()
  print "===> DB Backup"
  db_backup()
  print "===> Switch Symlinks"
  switch_symlinks()
  print "===> Set site offline"
  site_offline()
  print "===> DB Update"
  db_update()
  print "===> Set site online"
  site_online()

def sanitize_version(name):
  import re
  p = re.compile('\w+/%s_' % env.site_name)
  output = p.sub('', name, 1)
  return output

def setup_environment():
  env.web_root          = '/var/www'
  env.shared_dir        = '/var/lib/sitedata'

  env.site_symlink      = '%s/%s' % (env.web_root, env.site_name)
  env.db_backup_dir     = '%s/backups/%s' % (env.shared_dir, env.site_name)
  env.db_backup_file    = '%s_%s_db_%s.mysql' % (env.site_name, env.stage, time)
  env.scm_build_dir     = '/tmp/%s' % env.site_name
  env.releases_dir      = '%s/piwik' % env.web_root
  env.site_shared_config_dir = '%s/%s/config' % (env.shared_dir, env.site_name)
  env.site_shared_tmp_dir    = '%s/%s/tmp' % (env.shared_dir, env.site_name)
  env.log_dir           = '/var/log/sitelogs/%s' % env.site_name

  #santized_tag
  env.release_version   = sanitize_version(env.release_tag)
  env.release_name      = '%s_%s_%s' % (env.site_name, env.stage, env.release_version)
  env.release_archive   = '%s.tar.gz' % (env.release_name)
  env.release_dir       = '%s/%s' % (env.releases_dir, env.release_name)

@task
def test(stage,release_tag):
  env.stage = stage
  env.release_tag = release_tag
  setup_site_environment()
  setup_environment()
  # Test:
  #build_release(env.stage, env.release_tag)
  #execute(deploy_release_archive)
  #execute(deploy_release)
  #execute(db_backup)
  #execute(switch_symlinks)
  #execute(rollback)

@task
@parallel
def remoteRunTest():
  print "ENV %s" %(env.hosts)
  out = run('uname -n')
  print "Output %s"%(out)

@runs_once
def build_release(stage, release_tag='master', cache=False):
  print green('===> Building release...')
  # Ensure code directory exists
  with settings(warn_only=True):
    if local("test -d %s" % env.scm_build_dir).failed:
      local("git clone %s %s" % (env.scm_uri, env.scm_build_dir))

  with lcd(env.scm_build_dir):
    # put git status check here
    if (local("git pull", capture=True)).succeeded:
      release_tree = local('git show -s --format=%%h %s' % release_tag, True)
      local('git archive --remote="%s" --format tar %s | gzip > /tmp/%s' % (env.scm_uri, release_tree, env.release_archive))

@parallel
@roles('web')
def deploy_release_archive():
  # Push out the git archive
  with lcd('/tmp'):
    put('/tmp/' + env.release_archive, '/tmp/')

def deploy_release():
  with cd(env.web_root):
    # create release directory
    if run("test ! -d %s" % env.release_dir).succeeded:
      sudo("mkdir %s" % env.release_dir)
      if run("test -d %s" % env.release_dir).succeeded:
        sudo("tar -zxvf /tmp/%s -C %s --exclude=config" % (env.release_archive, env.release_dir))

  with cd('%s' % env.release_dir):
    # create config symlink
    with settings(warn_only=True):
      if run("test -d %s/config" % env.release_dir).succeeded:
        sudo("cp -v %s/global.ini.php %s" % (env.release_dir + '/config', env.site_shared_config_dir))
        sudo("cp -v %s/config.ini.sample.php %s" % (env.release_dir + '/config', env.site_shared_config_dir))
        sudo("rm -vrf %s/config" % env.release_dir)
      if run("test -L %s/config" % env.release_dir).failed:
        sudo("ln -s %s %s/config" % (env.site_shared_config_dir, env.release_dir))

    # create tmp symlink
    with settings(warn_only=True):
      if run("test -d %s/tmp" % env.release_dir).succeeded:
        sudo("rm -vrf %s/tmp" % env.release_dir)
      if run("test -L %s/tmp" % env.release_dir).failed:
        sudo("ln -s %s %s/tmp" % (env.site_shared_tmp_dir, env.release_dir))

# TODO: this should be run on the db server
#@roles('db')
@task
def db_backup(environment='prod'):
  #run(
  sudo(
    "mysqldump --single-transaction --opt -Q --host=%s  --user=%s --result-file=%s %s --password=%s" %
    (env.db_host, env.db_user, env.db_backup_dir + '/' + env.db_backup_file, env.db_name, env.db_pass)
  )
  #run(
  sudo(
    "gzip %s" % env.db_backup_dir + '/' + env.db_backup_file)

## disable piwik tracking and user interface
def site_offline():
  config_file = env.site_symlink + '/config/config.ini.php'

  # Turn on maintenance mode
  if (not contains(config_file, '\[General\]')):
    append(config_file, '[General]\nmaintenance_mode = 1', use_sudo=True)
  elif (not contains(config_file, 'maintenance_mode = 1')):
    sed(config_file, '\[General\]', '[General]\\nmaintenance_mode = 1', use_sudo=True)
  else:
    uncomment(config_file, 'maintenance_mode = 1', use_sudo=True, char=';')

  # Stop recording statistics
  if (not contains(config_file, '\[Tracker\]')):
    append(config_file, '[Tracker]\nrecord_statistics = 0', use_sudo=True)
  elif (not contains(config_file, 'record_statistics = 0')):
    sed(config_file, '\[Tracker\]', '[Tracker]\\nrecord_statistics = 0', use_sudo=True)
  else:
    uncomment(config_file, 'record_statistics = 0', use_sudo=True, char=';')

## enable piwik tracking and user interface
def site_online():
  config_file = env.site_symlink + '/config/config.ini.php'
  # Turn off maintenance mode; [General] section
  comment(config_file, 'maintenance_mode = 1', use_sudo=True, char=';')
  # Restart recording statistics; [Tracker] section
  comment(config_file, 'record_statistics = 0', use_sudo=True, char=';')

def db_update():
  sudo('php %s/index.php -- "module=CoreUpdater"' % env.site_symlink, user=env.site_user)
  # this doesn't return an error on error!

def switch_symlinks():
  new_previous = run('readlink %s' % env.site_symlink)
  new_current = env.release_dir

  if (new_previous != new_current):
    if run("test -d %s" % new_current).succeeded:
      sudo('ln -fns %s %s' % (new_current, env.site_symlink))
    if run("test -d %s" % env.site_symlink).succeeded:
      sudo('ln -fns %s %s' % (new_previous, env.site_symlink + '-previous'))

# TODO: def rollback_to_version()

def rollback():
  if run("test -L %s" % env.site_symlink + '-previous').succeeded:
    # swap symlinks
    previous = run('readlink %s' % env.site_symlink + '-previous')
    if run("test -L %s" % env.site_symlink).succeeded:
      current = run('readlink %s' % env.site_symlink)
      sudo('ln -fns %s %s' % (current, env.site_symlink + '-previous'))
    sudo('ln -fns %s %s' % (previous, env.site_symlink))

def check_dirs():
    # Create application specific directories
    print(green("Checking required directories are in place"))
    mkdir(env.releases_dir)
    mkdir(env.shared_config_dir)
    mkdir(env.shared_tmp_dir)
    #mkdir(env.app_log_dir)

def mkdir(dir, use_sudo=False):
    # Create a directory if it doesn't exist
    if (use_sudo):
      run('if [ ! -d %s ]; then mkdir -p %s; fi;' % (dir, dir))
    else:
      sudo('if [ ! -d %s ]; then mkdir -p %s; fi;' % (dir, dir))


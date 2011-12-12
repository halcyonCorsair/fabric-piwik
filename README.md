## Fabric Piwik

This fabric recipe provides tasks to deploy piwik from git.

Currently correct php, webserver, database setup is assumed.

## Requirements

* fabric 1.3.3
* python 2.7

This may or may not work with previous versions of fabric.  No guarantees.

## Usage

Copy sitedef.py.example to sitedef.py with the details of you installation, then simply:

  $ fab do_release:stage='production',release_tag='tag'

## TODO / Known Issues

* Multi-server support -- in progress; it may or may not work as expected
* Rollback should restore database from backup

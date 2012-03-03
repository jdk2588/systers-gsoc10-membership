# -*- python -*-

# Copyright (C) 1998,1999,2000,2001,2002 by the Free Software Foundation, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software 
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

"""This module contains your site-specific settings.

From a brand new distribution it should be copied to mm_cfg.py.  If you
already have an mm_cfg.py, be careful to add in only the new settings you
want.  Mailman's installation procedure will never overwrite your mm_cfg.py
file.

The complete set of distributed defaults, with documentation, are in the file
Defaults.py.  In mm_cfg.py, override only those you want to change, after the

  from Defaults import *

line (see below).

Note that these are just default settings; many can be overridden via the
administrator and user interfaces on a per-list or per-user basis.

"""

###############################################
# Here's where we get the distributed defaults.

from Defaults import *

##################################################
# Put YOUR site-specific settings below this line.
MTA = 'Postfix'
MAILMAN_SITE_LIST = 'systers-admin'
PENDING_REQUEST_LIFE = days(30)

# Add preference bit for Dlist functionality
SubscribedToNewThreads = 512
# make it the default
DEFAULT_NEW_MEMBER_OPTIONS = DEFAULT_NEW_MEMBER_OPTIONS | SubscribedToNewThreads

# Insert Dlist into global pipeline before CookHeaders
GLOBAL_PIPELINE.insert(GLOBAL_PIPELINE.index("CookHeaders"), "Dlists")

# Add dlistrunner delivery queue
QRUNNERS.append(('DlistRunner', 1))
DLISTQUEUE_DIR = os.path.join(QUEUE_DIR, 'dlist')

# to solve the problem of not being able to create lists from www.host.doman
#  (as opposed to host.domain)
#VIRTUAL_HOST_OVERVIEW = Off
STORM_DB = 'postgres'
STORM_MEMBER_DB_USER = 'mailman'
STORM_MEMBER_DB_PASS = 'mailman'
STORM_MEMBER_DB_HOST = 'localhost'
STORM_MEMBER_DB_NAME = 'mailman_members'
STORM_DB_USER = 'mailman'
STORM_DB_PASS = 'mailman'
STORM_DB_HOST = 'localhost'

##Following is for testing purposes only##

DEFAULT_URL_HOST = 'jdk2588.com'
DEFAULT_EMAIL_HOST = 'jdk2588.com'

add_virtualhost(DEFAULT_URL_HOST,DEFAULT_EMAIL_HOST)
DEBUG_MODE=False

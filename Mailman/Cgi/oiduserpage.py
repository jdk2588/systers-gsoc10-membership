# Copyright (C) 1998-2008 by the Free Software Foundation, Inc.
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301,
# USA.

"""Produce and handle the member options."""

import sys
import os
import cgi
import signal
import urllib
from types import ListType

from Mailman import mm_cfg
from Mailman import Utils
from Mailman import MailList
from Mailman import Errors
from Mailman import MemberAdaptor
from Mailman import i18n
from Mailman import SecurityManager
from Mailman.htmlformat import *
from Mailman.Logging.Syslog import syslog
from Mailman import DlistUtils  # Added for dlists
import string                   # Added for dlists
import Cookie                   # Added for dlists
import psycopg2 as pgdb
#import openidconsumer 

SLASH = '/'
SETLANGUAGE = -1

# Set up i18n
_ = i18n._
i18n.set_language(mm_cfg.DEFAULT_SERVER_LANGUAGE)

try:
    True, False
except NameError:
    True = 1
    False = 0

def main():
    doc = Document()
    doc.set_language(mm_cfg.DEFAULT_SERVER_LANGUAGE)
    parts = Utils.GetPathPieces()
    lenparts = parts and len(parts)
    if not parts or lenparts < 1:
        title = _('CGI script error')
        doc.SetTitle(title)
        doc.AddItem(Header(2, title))
        doc.addError(_('Invalid options to CGI script.'))
        doc.AddItem('<hr>')
        doc.AddItem(MailmanLogo())
        print doc.Format()
        return
    cgidata = cgi.FieldStorage(keep_blank_values=1)
    
    listinfo = mm_cfg.DEFAULT_URL_HOST
    oidc = mm_cfg.DEFAULT_OID_CONSUMER

    hostname = mm_cfg.DEFAULT_URL_HOST
    filename = "/usr/local/mailman/Mailman/.save.txt"
    file = open(filename, 'r')
    safeuser = file.read()
 #   safer = safeuser.doProcess()
    title = _('List subscriptions for %(safeuser)s on %(hostname)s')
    doc.SetTitle(title)
    doc.AddItem(Header(2, title))
    doc.AddItem(_('''Click on a link to visit your options page for the
    requested mailing list.'''))
    
    conn = pgdb.connect(host='localhost', database='mailman_members', user='mailman', password='mailman')
    cursor = conn.cursor()   
    command = cursor.execute("SELECT listname FROM mailman_test where address='%s' and openid = 't' ;" % (safeuser))     
    data = cursor.fetchall()
    item = len(data)
    for i in range(0, item):
        dataval =  data[i][0][0].upper() + data[i][0][1:]
        doc.AddItem('\n <p>Access your all subscribed list. Click Here <a href = "http://%s/mailman/client/%s/%s"> %s </a> .</p> \n' % (mm_cfg.DEFAULT_URL_HOST,data[i][0],safeuser,dataval))
        # Troll through all the mailing lists that match host_name and see if
        # the user is a member.  If so, add it to the list.
    onlists = []
    
#    for gmlist in lists_of_member(safeuser) :
#            url = gmlist.GetOptionsURL(safeuser)
#            link = Link(url, gmlist.real_name)
#            onlists.append((gmlist.real_name, link))
#    onlists.sort()
#    items = OrderedList(*[link for name, link in onlists])
#    doc.AddItem(items)
    print doc.Format()
    return
def lists_of_member(safeuser):
    hostname = mm_cfg.DEFAULT_URL_HOST
    onlists = []
    for listname in Utils.list_names():
        # The current list will always handle things in the mainline
        if listname == Utils.list_names():
            continue
        glist = MailList.MailList(listname, lock=0)
        if glist.host_name <> hostname:
            continue
        if not glist.isMember(safeuser):
            continue
        onlists.append(glist)
    return onlists

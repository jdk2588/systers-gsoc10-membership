# Copyright (C) 1998-2003 by the Free Software Foundation, Inc.
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

"""Produce listinfo page, primary web entry-point to mailing lists.
"""

# No lock needed in this script, because we don't change data.

import os
import cgi

from Mailman import mm_cfg
from Mailman import Utils
from Mailman import MailList
from Mailman import Errors
from Mailman import i18n
from Mailman.htmlformat import *
from Mailman.Logging.Syslog import syslog
from Mailman import DlistUtils  # Added to support dlists

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from urlparse import urlparse

import time
import Cookie
import cgitb
import sys

# Set up i18n
_ = i18n._
i18n.set_language(mm_cfg.DEFAULT_SERVER_LANGUAGE)




def main():
    parts = Utils.GetPathPieces()
    if not parts:
        listinfo_overview()
        return

    listname = parts[0].lower()
    try:
        mlist = MailList.MailList(listname, lock=0)
    except Errors.MMListError, e:
        # Avoid cross-site scripting attacks
        safelistname = Utils.websafe(listname)
        listinfo_overview(_('No such list <em>%(safelistname)s</em>'))
        syslog('error', 'No such list "%s": %s', listname, e)
        return

    # See if the user want to see this page in other language
    cgidata = cgi.FieldStorage()
    language = cgidata.getvalue('language')
    if not Utils.IsLanguage(language):
        language = mlist.preferred_language
    i18n.set_language(language)
    list_listinfo(mlist, language)


def listinfo_overview(msg=''):
    # Present the general listinfo overview
    hostname = Utils.get_domain()
    # Set up the document and assign it the correct language.  The only one we
    # know about at the moment is the server's default.
    doc = Document()
    doc.set_language(mm_cfg.DEFAULT_SERVER_LANGUAGE)

    legend = _("%(hostname)s Mailing Lists")
    doc.SetTitle(legend)

    table = Table(border=0, width="100%")
    table.AddRow([Center(Header(2, legend))])
    table.AddCellInfo(table.GetCurrentRowIndex(), 0, colspan=2,
                      bgcolor=mm_cfg.WEB_HEADER_COLOR)

    # Skip any mailing lists that isn't advertised.
    advertised = []
    listnames = Utils.list_names()
    listnames.sort()

    for name in listnames:
        mlist = MailList.MailList(name, lock=0)
        if mlist.advertised:
            if mm_cfg.VIRTUAL_HOST_OVERVIEW and \
                   mlist.web_page_url.find(hostname) == -1:
                # List is for different identity of this host - skip it.
                continue
            else:
                advertised.append((mlist.GetScriptURL('listinfo'),
                                   mlist.real_name,
                                   mlist.description))
    if msg:
        greeting = FontAttr(msg, color="ff5060", size="+1")
    else:
        greeting = FontAttr(_('Welcome!'), size='+2')

    welcome = [greeting]
    mailmanlink = Link(mm_cfg.MAILMAN_URL, _('Mailman')).Format()
    if not advertised:
        welcome.extend(
            _('''<p>There currently are no publicly-advertised
            %(mailmanlink)s mailing lists on %(hostname)s.'''))
    else:
        welcome.append(
            _('''<p>Below is a listing of all the public mailing lists on
            %(hostname)s.  Click on a list name to get more information about
            the list, or to subscribe, unsubscribe, and change the preferences
            on your subscription.'''))

    # set up some local variables
    adj = msg and _('right') or ''
    siteowner = Utils.get_site_email()
    welcome.extend(
        (_(''' To visit the general information page for an unadvertised list,
        open a URL similar to this one, but with a '/' and the %(adj)s
        list name appended.
        <p>List administrators, you can visit '''),
         Link(Utils.ScriptURL('admin'),
              _('the list admin overview page')),
         _(''' to find the management interface for your list.
         <p>If you are having trouble using the lists, please contact '''),
         Link('mailto:' + siteowner, siteowner),
         '.<p>'))
    
    welcome.extend(
        (_('''Users who are subscribed to one of the Mailing List can use OpenID to login with common credentials,
        to access all their subscribed List.
        <p> To register OpenID  '''),
        Link(Utils.ScriptURL('openidreg'),
              _('Click Here')),
        _(''' to use OpenID for Systers'''),
        '.<p>'))   
    table.AddRow([apply(Container, welcome)])
    table.AddCellInfo(max(table.GetCurrentRowIndex(), 0), 0, colspan=2)

    if advertised:
        table.AddRow(['&nbsp;', '&nbsp;'])
        table.AddRow([Bold(FontAttr(_('List'), size='+2')),
                      Bold(FontAttr(_('Description'), size='+2'))
                      ])
        highlight = 1
        for url, real_name, description in advertised:
            table.AddRow(
                [Link(url, Bold(real_name)),
                      description or Italic(_('[no description available]'))])
            if highlight and mm_cfg.WEB_HIGHLIGHT_COLOR:
                table.AddRowInfo(table.GetCurrentRowIndex(),
                                 bgcolor=mm_cfg.WEB_HIGHLIGHT_COLOR)
            highlight = not highlight

    doc.AddItem(table)
    doc.AddItem('<hr>')
    doc.AddItem(MailmanLogo())
    print doc.Format()



def list_listinfo(mlist, lang):
    # Generate list specific listinfo
    doc = HeadlessDocument()
    doc.set_language(lang)

    replacements = mlist.GetStandardReplacements(lang)
    
    # needed for the sending email instructions further down, added by Systers
    listName = replacements['<mm-list-name>'].lower()
    hostName = replacements['<mm-host>']
    postAddr = replacements['<mm-posting-addr>']

    if not mlist.digestable or not mlist.nondigestable:
        replacements['<mm-digest-radio-button>'] = ""
        replacements['<mm-undigest-radio-button>'] = ""
        replacements['<mm-digest-question-start>'] = '<!-- '
        replacements['<mm-digest-question-end>'] = ' -->'
    else:
        replacements['<mm-digest-radio-button>'] = mlist.FormatDigestButton()
        replacements['<mm-undigest-radio-button>'] = \
                                                   mlist.FormatUndigestButton()
        replacements['<mm-digest-question-start>'] = ''
        replacements['<mm-digest-question-end>'] = ''
    replacements['<mm-plain-digests-button>'] = \
                                              mlist.FormatPlainDigestsButton()
    replacements['<mm-mime-digests-button>'] = mlist.FormatMimeDigestsButton()
    replacements['<mm-subscribe-box>'] = mlist.FormatBox('email', size=30)
    replacements['<mm-subscribe-button>'] = mlist.FormatButton(
        'email-button', text=_('Subscribe'))
    replacements['<mm-new-password-box>'] = mlist.FormatSecureBox('pw')
    replacements['<mm-confirm-password>'] = mlist.FormatSecureBox('pw-conf')
    replacements['<mm-subscribe-form-start>'] = mlist.FormatFormStart(
        'subscribe')

    # If activated, the content and presence of questions and a field to answer them. Added by Systers.
    try:
        if mlist.essay_enabled:
            replacements['<mm-questions>'] = """<TR>
            <TD COLSPAN="3">""" + mlist.questions
            replacements['<mm-essay-box>'] = TextArea('essay', '', rows=8, cols=60).Format() + """        </TD></TR>"""# Added to support subscribe essays
        else:
            replacements['<mm-questions>'] = ''
            replacements['<mm-essay-box>'] = ''
    
        # Instruction text for sending an email to the list, depending on dlist or not.
        if mlist.dlists_enabled:
            replacements['<mm-new-email-list>'] = """The mailing list is organized around <em>conversations</em>.  To begin a new conversation, send email to <a href="mailto:%s+new@%s">%s+new@%s</a>.
            
            Alternately, if you would like to specify a name for your new conversation, send your message to %s+new+<em>name</em>@%s, replacing <em>name</em> with the name you would like (e.g., %s+new+greetings@%s).<p>
            
            <p>To continue an existing conversation, simply use your mailer's "reply-all" command.</p>""" % (listName, hostName, listName, hostName, listName, hostName, listName, hostName)
        else:
            replacements['<mm-new-email-list>'] = 'To post a message to all the list members, send email to <A HREF="mailto:%s">%s</A>.' % (postAddr, postAddr)
    except:         # added to make old lists still work after implementation of new features
        try:
            replacements['<mm-questions>'] = """<TR>
            <TD COLSPAN="3">""" + mlist.questions
        except:
            replacements['<mm-questions>'] = """<TR>
            <TD COLSPAN="3">""" #+ #mlist.questions isn't defined here... use template quesions?
        replacements['<mm-essay-box>'] = """<br>""" + TextArea('essay', '', rows=8, cols=60).Format() + """        </TD></TR>"""
        replacements['<mm-new-email-list>'] = """The mailing list is organized around <em>conversations</em>.  To begin a new conversation, send email to <a href="mailto:%s+new@%s">%s+new@%s</a>.
        
        Alternately, if you would like to specify a name for your new conversation, send your message to %s+new+<em>name</em>@%s, replacing <em>name</em> with the name you would like (e.g., %s+new+greetings@%s).<p>
        
        <p>To continue an existing conversation, simply use your mailer's "reply-all" command.</p>""" % (listName, hostName, listName, hostName, listName, hostName, listName, hostName)

    # Roster form substitutions
    replacements['<mm-roster-form-start>'] = mlist.FormatFormStart('roster')
    replacements['<mm-roster-option>'] = mlist.FormatRosterOptionForUser(lang)
    # OpenID form subtitutions
    replacements['<mm-openid-form-start>'] = mlist.FormatFormStarts()
    replacements['<mm-openid-option>'] = mlist.FormatOpenIDForUser(lang)
    # Options form substitutions
    replacements['<mm-options-form-start>'] = mlist.FormatFormStart('options')
    replacements['<mm-editing-options>'] = mlist.FormatEditingOption(lang)
    replacements['<mm-info-button>'] = SubmitButton('UserOptions',
                                                    _('Edit Options')).Format()
    # If only one language is enabled for this mailing list, omit the choice
    # buttons.
    if len(mlist.GetAvailableLanguages()) == 1:
        displang = ''
    else:
        displang = mlist.FormatButton('displang-button',
                                      text = _("View this page in"))
    replacements['<mm-displang-box>'] = displang
    replacements['<mm-lang-form-start>'] = mlist.FormatFormStart('listinfo')
    replacements['<mm-fullname-text>'] = """      <tr>
    <td bgcolor="#dddddd" width="55%">Your name:</td>
    <td width="33%">"""
    replacements['<mm-fullname-box>'] = mlist.FormatBox('fullname', size=30) + """</td>
    <TD WIDTH="12%">&nbsp;</TD></TR>"""

    # make the listinfo page using the template
    doc.AddItem(mlist.ParseTags('listinfo_allow_essays.html', replacements, lang))
    print doc.Format()



if __name__ == "__main__":
    main()

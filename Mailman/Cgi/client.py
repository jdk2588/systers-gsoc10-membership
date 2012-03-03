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
import psycopg2
from types import ListType

from Mailman import mm_cfg
from Mailman import Utils
from Mailman import MailList
from Mailman import Errors
from Mailman import MemberAdaptor
from Mailman import i18n
from Mailman.htmlformat import *
from Mailman.Logging.Syslog import syslog
from Mailman import DlistUtils  # Added for dlists
import string                   # Added for dlists
import Cookie                   # Added for dlists
from Mailman.mm_cfg import DEBUG_MODE

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

    # get the list and user's name
    listname = parts[0].lower()

## Added to support CGI data with override URL (for dlists)
    index = listname.find('&')
    if index != -1:
        listname = listname[:index]
    ## End added for dlists

    # open list
    try:
        mlist = MailList.MailList(listname, lock=0)
    except Errors.MMListError, e:
        # Avoid cross-site scripting attacks
        safelistname = Utils.websafe(listname)
        title = _('CGI script error')
        doc.SetTitle(title)
        doc.AddItem(Header(2, title))
        doc.addError(_('No such list <em>%(safelistname)s</em>'))
        doc.AddItem('<hr>')
        doc.AddItem(MailmanLogo())
        print doc.Format()
        syslog('error', 'No such list "%s": %s\n', listname, e)
        return

    # The total contents of the user's response
    cgidata = cgi.FieldStorage(keep_blank_values=1)
    # Set the language for the page.  If we're coming from the listinfo cgi,
    # we might have a 'language' key in the cgi data.  That was an explicit
    # preference to view the page in, so we should honor that here.  If that's
    # not available, use the list's default language.
    language = cgidata.getvalue('language')
    if not Utils.IsLanguage(language):
        language = mlist.preferred_language
    i18n.set_language(language)
    doc.set_language(language)

    if lenparts < 2:
        user = cgidata.getvalue('email')
        # want to infer user (if possible) to make thread unsubscribe (dlists)
        # as painless as possible
	if not user:                            # Added for dlists
	    user = mlist.InferUserFromCookies()  # Added for dlists
        if not user:
            # If we're coming from the listinfo page and we left the email
            # address field blank, it's not an error.  Likewise if we're
            # coming from anywhere else. Only issue the error if we came
            # via one of our buttons.
            if (cgidata.getvalue('login') or cgidata.getvalue('login-unsub') or cgidata.getvalue('login-remind') or cgidata.getvalue('conv-unsub')):
                doc.addError(_('No address given'))
            # the cgidata contains possible information about wishing to (un)subscribe from a conversation. Added by Systers.
            loginpage(mlist, doc, None, language, cgidata)
            print doc.Format()
            return
    else:
        user = Utils.LCDomain(Utils.UnobscureEmail(SLASH.join(parts[1:])))

    # Avoid cross-site scripting attacks
    safeuser = Utils.websafe(user)
    try:
        Utils.ValidateEmail(user)
    except Errors.EmailAddressError:
        doc.addError(_('Illegal Email Address: %(safeuser)s'))
        loginpage(mlist, doc, None, language, cgidata)
        print doc.Format()
        return
    # Sanity check the user, but only give the "no such member" error when
    # using public rosters, otherwise, we'll leak membership information.
    if not mlist.isMember(user) and mlist.private_roster == 0:
        doc.addError(_('No such member: %(safeuser)s.'))
        loginpage(mlist, doc, None, language, cgidata)
        print doc.Format()
        return

    # Find the case preserved email address (the one the user subscribed with)
    lcuser = user.lower()
    try:
        cpuser = mlist.getMemberCPAddress(lcuser)
    except Errors.NotAMemberError:
        # This happens if the user isn't a member but we've got private rosters
        cpuser = None
    if lcuser == cpuser:
        cpuser = None

    # And now we know the user making the request, so set things up to for the
    # user's stored preferred language, overridden by any form settings for
    # their new language preference.
    userlang = cgidata.getvalue('language')
    if not Utils.IsLanguage(userlang):
        userlang = mlist.getMemberLanguage(user)
    doc.set_language(userlang)
    i18n.set_language(userlang)

    # See if this is VARHELP on topics.
    varhelp = None
    if cgidata.has_key('VARHELP'):
        varhelp = cgidata['VARHELP'].value
    elif os.environ.get('QUERY_STRING'):
        # POST methods, even if their actions have a query string, don't get
        # put into FieldStorage's keys :-(
        qs = cgi.parse_qs(os.environ['QUERY_STRING']).get('VARHELP')
        if qs and type(qs) == types.ListType:
            varhelp = qs[0]
    if varhelp:
        topic_details(mlist, doc, user, cpuser, userlang, varhelp)
        return

    # Are we processing an unsubscription request from the login screen?
    if cgidata.has_key('login-unsub'):
        # Because they can't supply a password for unsubscribing, we'll need
        # to do the confirmation dance.
        if mlist.isMember(user):
            # We must acquire the list lock in order to pend a request.
            try:
                mlist.Lock()
                # If unsubs require admin approval, then this request has to
                # be held.  Otherwise, send a confirmation.
                if mlist.unsubscribe_policy:
                    mlist.HoldUnsubscription(user)
                    doc.addError(_("""Your unsubscription request has been
                    forwarded to the list administrator for approval."""),
                                 tag='')
                else:
                    mlist.ConfirmUnsubscription(user, userlang)
                    doc.addError(_('The confirmation email has been sent.'),
                                 tag='')
                mlist.Save()
            finally:
                mlist.Unlock()
        else:
            # Not a member
            if mlist.private_roster == 0:
                # Public rosters
                doc.addError(_('No such member: %(safeuser)s.'))
            else:
                syslog('mischief',
                       'Unsub attempt of non-member w/ private rosters: %s',
                       user)
                doc.addError(_('The confirmation email has been sent.'),
                             tag='')
        loginpage(mlist, doc, user, language)
        print doc.Format()
        return

    # Are we processing an unsubscription request from the login screen? Part with conversation added by Systers.
    if cgidata.has_key('conv-unsub'):
	subscriber = DlistUtils.Subscriber(mlist)
	override = DlistUtils.Override(mlist)
        # Because they can't supply a password for unsubscribing, we'll need
        # to do the confirmation dance.
        if mlist.isMember(user):
            # We must acquire the list lock in order to pend a request.
            try:
                mlist.Lock()
                # If unsubs require admin approval, then this request has to
                # be held.  Otherwise, send a confirmation.
                subscriberID = subscriber.getSubscriber_id_raw(user)
                thread_reference = cgidata.getvalue('override')
                preference = int(cgidata.getvalue('preference'))
                override.override_from_web(subscriberID, thread_reference, preference)
                if preference == 0:
                        subscribe_string = "unsubscribed"
                        preposition = "from"
                        unsubscribe_string = "subscribe"
                        undo = 1
                else:
                    subscribe_string = "subscribed"
                    preposition = "to"
                    unsubscribe_string = "unsubscribe"
                    undo = 0
                web_addr = override.overrideURL(mlist.internal_name(), mlist.host_name, thread_reference, undo)
                link_url = '<a href="%s">%s</a>' % (web_addr, web_addr) 
                doc.addError(_('You have been %s %s the conversation. To %s again, please visit %s' % (subscribe_string, preposition, unsubscribe_string, link_url)), tag='')
                #doc.addError(_('The confirmation email has been sent.'), tag='')
                mlist.Save()
            finally:
                mlist.Unlock()
        else:
            # Not a member
            if mlist.private_roster == 0:
                # Public rosters
                doc.addError(_('No such member: %(safeuser)s.'))
            else:
                syslog('mischief',
                       'Unsub attempt of non-member w/ private rosters: %s',
                       user)
                doc.addError(_('The confirmation email has been sent.'),
                             tag='')    # This is misleading, this never happens which is bad if someone just happend to type in the wrong address (eg. his/her old address if they changed it).
        loginpage(mlist, doc, user, language)
        print doc.Format()
        return

    # Are we processing a password reminder from the login screen?
    if cgidata.has_key('login-remind'):
        if mlist.isMember(user):
            mlist.MailUserPassword(user)
            doc.addError(
                _('A reminder of your password has been emailed to you.'),
                tag='')
        else:
            # Not a member
            if mlist.private_roster == 0:
                # Public rosters
                doc.addError(_('No such member: %(safeuser)s.'))
            else:
                syslog('mischief',
                       'Reminder attempt of non-member w/ private rosters: %s',
                       user)
                doc.addError(
                    _('A reminder of your password has been emailed to you.'),
                    tag='')
        loginpage(mlist, doc, user, language)
        print doc.Format()
        return

    # Get the password from the form.
    password = cgidata.getvalue('password', '').strip()
    # Check authentication.  We need to know if the credentials match the user
    # or the site admin, because they are the only ones who are allowed to
    # change things globally.  Specifically, the list admin may not change
    # values globally.
    if mm_cfg.ALLOW_SITE_ADMIN_COOKIES:
          user_or_siteadmin_context = (mm_cfg.AuthUser, mm_cfg.AuthSiteAdmin)
    else:
        # Site and list admins are treated equal so that list admin can pass
        # site admin test. :-(
          user_or_siteadmin_context = (mm_cfg.AuthUser,)
          is_user_or_siteadmin = mlist.WebAuthenticates(
          user_or_siteadmin_context, password, user)
    # Authenticate, possibly using the password supplied in the login page
    if not is_user_or_siteadmin and \
       not mlist.WebAuthenticates((mm_cfg.AuthListAdmin,
                                  mm_cfg.AuthSiteAdmin),
                                 password, user):
        # Not authenticated, so throw up the login page again.  If they tried
        # to authenticate via cgi (instead of cookie), then print an error
        # message.
       if cgidata.has_key('password'):
            doc.addError(_('Authentication failed or Not a Subscribed User.'))
            # So as not to allow membership leakage, prompt for the email
            # address and the password here.
            if mlist.private_roster <> 0:
                syslog('mischief',
                       'Login failure with private rosters: %s',
                       user)
                user = None
       loginpage(mlist, doc, user, language, cgidata)
       print doc.Format()
       return 

    # From here on out, the user is okay to view and modify their membership
    # options.  The first set of checks does not require the list to be
    # locked.

    if cgidata.has_key('logout'):
        print mlist.ZapCookies(mm_cfg.AuthUser, user)
        loginpage(mlist, doc, user, language, cgidata)
        print doc.Format()
        return

    if cgidata.has_key('emailpw'):
        mlist.MailUserPassword(user)
        options_page(
            mlist, doc, user, cpuser, userlang,
            _('A reminder of your password has been emailed to you.'))
        print doc.Format()
        return

    if cgidata.has_key('othersubs'):
        # Only the user or site administrator can view all subscriptions.
        if not is_user_or_siteadmin:
            doc.addError(_("""The list administrator may not view the other
            subscriptions for this user."""), _('Note: '))
            options_page(mlist, doc, user, cpuser, userlang)
            print doc.Format()
            return
        hostname = mlist.host_name
        title = _('List subscriptions for %(safeuser)s on %(hostname)s')
        doc.SetTitle(title)
        doc.AddItem(Header(2, title))
        doc.AddItem(_('''Click on a link to visit your options page for the
        requested mailing list.'''))

        # Troll through all the mailing lists that match host_name and see if
        # the user is a member.  If so, add it to the list.
        onlists = []
        for gmlist in lists_of_member(mlist, user) + [mlist]:
            url = gmlist.GetOpenIDURL(user)
            link = Link(url, gmlist.real_name)
            onlists.append((gmlist.real_name, link))
        onlists.sort()
        items = OrderedList(*[link for name, link in onlists])
        doc.AddItem(items)
        print doc.Format()
        return

    if cgidata.has_key('discauth'):
        # Only the user or site administrator can disable this thing.
        if not is_user_or_siteadmin:
            doc.addError(_("""The list administrator cannot disable this option."""), _('Note: '))
            options_page(mlist, doc, user, cpuser, userlang)
            print doc.Format()
            return

        hostname = mlist.host_name
        title = _('Common Authentication  disabled for %(safeuser)s')
        doc.SetTitle(title)
        doc.AddItem(Header(2, title))
        doc.AddItem(_('''Common Authentication is disabled for your account.'''))

        conn = psycopg2.connect(host='localhost', database='mailman_members', user='mailman', password='mailman')
        cursor = conn.cursor()   
        command = cursor.execute("SELECT listname,address,openid FROM mailman_test where address = '%s' and openid ='t';" % (user)) 
    
        data = cursor.fetchall()
        item = len(data)
        if data!=[]:
          for i in range(0, item):
                cursor.execute("UPDATE mailman_test SET openid='0' WHERE listname = '%s' AND address = '%s'" % (data[i][0], data[i][1]))
                conn.commit()
        else:
                doc.addError(_("""The list administrator cannot disable the Authentication for this user."""), _('Note: '))
        print doc.Format()
        return

    if cgidata.has_key('changeauth'):
        # Only the user or site administrator can view all subscriptions.
        newcauthpw = cgidata.getvalue('newcauthpw')
        confcauthpw = cgidata.getvalue('confcauthpw')
        if not is_user_or_siteadmin:
            doc.addError(_("""The list administrator cannot disable this option."""), _('Note: '))
            options_page(mlist, doc, user, cpuser, userlang)
            print doc.Format()
            return
        if not newcauthpw or not confcauthpw:
            options_page(mlist, doc, user, cpuser, userlang,
                         _('Passwords may not be blank'))
            print doc.Format()
            return
        
        # Troll through all the mailing lists that match host_name and see if
        # the user is a member.  If so, add it to the list.
        
        if newcauthpw == confcauthpw:
           conn = psycopg2.connect(host='localhost', database='mailman_members', user='mailman', password='mailman')
           cursor = conn.cursor()   
           listaddr = mlist.FormatLists()
           command = cursor.execute("SELECT listname,address,password,openid FROM mailman_test where address = '%s' and listname='%s';" % (user, listaddr)) 
    
           data = cursor.fetchall()
           item = len(data)
           if data!=[]:
              for i in range(0, item):
                cursor.execute("UPDATE mailman_test SET openid='0' WHERE address = '%s' and openid ='1'" % (user))
                conn.commit()
                cursor.execute("UPDATE mailman_test SET password='%s' , openid ='1' WHERE address = '%s' and listname='%s'" % (newcauthpw, user, listaddr))
                conn.commit()
                print mlist.MakeCookies(mm_cfg.AuthUser, user)
                options_page(mlist, doc, user, cpuser, userlang,
                     _('Password successfully changed.'))
           else:
                doc.addError(_("""The list administrator cannot disable the Authentication for this user."""), _('Note: '))
        else:
                options_page(mlist, doc, user, cpuser, userlang,
                         _('Passwords Mismatch'))
        print doc.Format()
        return

    if cgidata.has_key('change-of-address'):
        # We could be changing the user's full name, email address, or both.
        # Watch out for non-ASCII characters in the member's name.
        membername = cgidata.getvalue('fullname')
        # Canonicalize the member's name
        membername = Utils.canonstr(membername, language)
        newaddr = cgidata.getvalue('new-address')
        confirmaddr = cgidata.getvalue('confirm-address')

        oldname = mlist.getMemberName(user)
        set_address = set_membername = 0

        # See if the user wants to change their email address globally.  The
        # list admin is /not/ allowed to make global changes.
        globally = cgidata.getvalue('changeaddr-globally')
        if globally and not is_user_or_siteadmin:
            doc.addError(_("""The list administrator may not change the names
            or addresses for this user's other subscriptions.  However, the
            subscription for this mailing list has been changed."""),
                         _('Note: '))
            globally = False
        # We will change the member's name under the following conditions:
        # - membername has a value
        # - membername has no value, but they /used/ to have a membername
        if membername and membername <> oldname:
            # Setting it to a new value
            set_membername = 1
        if not membername and oldname:
            # Unsetting it
            set_membername = 1
        # We will change the user's address if both newaddr and confirmaddr
        # are non-blank, have the same value, and aren't the currently
        # subscribed email address (when compared case-sensitively).  If both
        # are blank, but membername is set, we ignore it, otherwise we print
        # an error.
        msg = ''
        if newaddr and confirmaddr:
            if newaddr <> confirmaddr:
                options_page(mlist, doc, user, cpuser, userlang,
                             _('Addresses did not match!'))
                print doc.Format()
                return
            if newaddr == cpuser:
                options_page(mlist, doc, user, cpuser, userlang,
                             _('You are already using that email address'))
                print doc.Format()
                return
            # If they're requesting to subscribe an address which is already a
            # member, and they're /not/ doing it globally, then refuse.
            # Otherwise, we'll agree to do it globally (with a warning
            # message) and let ApprovedChangeMemberAddress() handle already a
            # member issues.
            if mlist.isMember(newaddr):
                safenewaddr = Utils.websafe(newaddr)
                if globally:
                    listname = mlist.real_name
                    msg += _("""\
The new address you requested %(newaddr)s is already a member of the
%(listname)s mailing list, however you have also requested a global change of
address.  Upon confirmation, any other mailing list containing the address
%(safeuser)s will be changed. """)
                    # Don't return
                else:
                    options_page(
                        mlist, doc, user, cpuser, userlang,
                        _('The new address is already a member: %(newaddr)s'))
                    print doc.Format()
                    return
            set_address = 1
        elif (newaddr or confirmaddr) and not set_membername:
            options_page(mlist, doc, user, cpuser, userlang,
                         _('Addresses may not be blank'))
            print doc.Format()
            return

        # Standard sigterm handler.
        def sigterm_handler(signum, frame, mlist=mlist):
            mlist.Unlock()
            sys.exit(0)

        signal.signal(signal.SIGTERM, sigterm_handler)
        if set_address:
            if cpuser is None:
                cpuser = user
            # Register the pending change after the list is locked
            msg += _('A confirmation message has been sent to %(newaddr)s. ')
            mlist.Lock()
            try:
                try:
                    mlist.ChangeMemberAddress(cpuser, newaddr, globally)
                    mlist.Save()
                finally:
                    mlist.Unlock()
            except Errors.MMBadEmailError:
                msg = _('Bad email address provided')
            except Errors.MMHostileAddress:
                msg = _('Illegal email address provided')
            except Errors.MMAlreadyAMember:
                msg = _('%(newaddr)s is already a member of the list.')
            except Errors.MembershipIsBanned:
                owneraddr = mlist.GetOwnerEmail()
                msg = _("""%(newaddr)s is banned from this list.  If you
                      think this restriction is erroneous, please contact
                      the list owners at %(owneraddr)s.""")

        if set_membername:
            mlist.Lock()
            try:
                mlist.ChangeMemberName(user, membername, globally)
                mlist.Save()
            finally:
                mlist.Unlock()
            msg += _('Member name successfully changed. ')

        options_page(mlist, doc, user, cpuser, userlang, msg)
        print doc.Format()
        return

    if cgidata.has_key('changepw'):
        # Is this list admin and is list admin allowed to change passwords.
        if not (is_user_or_siteadmin
                or mm_cfg.OWNERS_CAN_CHANGE_MEMBER_PASSWORDS):
            doc.addError(_("""The list administrator may not change the
                    password for a user."""))
            options_page(mlist, doc, user, cpuser, userlang)
            print doc.Format()
            return
        newpw = cgidata.getvalue('newpw')
        confirmpw = cgidata.getvalue('confpw')
        if not newpw or not confirmpw:
            options_page(mlist, doc, user, cpuser, userlang,
                         _('Passwords may not be blank'))
            print doc.Format()
            return
        if newpw <> confirmpw:
            options_page(mlist, doc, user, cpuser, userlang,
                         _('Passwords did not match!'))
            print doc.Format()
            return

        # See if the user wants to change their passwords globally, however
        # the list admin is /not/ allowed to change passwords globally.
        pw_globally = cgidata.getvalue('pw-globally')
        if pw_globally and not is_user_or_siteadmin:
            doc.addError(_("""The list administrator may not change the
            password for this user's other subscriptions.  However, the
            password for this mailing list has been changed."""),
                         _('Note: '))
            pw_globally = False

        mlists = [mlist]

        if pw_globally:
            mlists.extend(lists_of_member(mlist, user))

        for gmlist in mlists:
            change_password(gmlist, user, newpw, confirmpw)

        # Regenerate the cookie so a re-authorization isn't necessary
        print mlist.MakeCookies(mm_cfg.AuthUser, user)
        options_page(mlist, doc, user, cpuser, userlang,
                     _('Password successfully changed.'))
        print doc.Format()
        return

    if cgidata.has_key('unsub'):
        # Was the confirming check box turned on?
        if not cgidata.getvalue('unsubconfirm'):
            options_page(
                mlist, doc, user, cpuser, userlang,
                _('''You must confirm your unsubscription request by turning
                on the checkbox below the <em>Unsubscribe</em> button.  You
                have not been unsubscribed!'''))
            print doc.Format()
            return

        # Standard signal handler
        def sigterm_handler(signum, frame, mlist=mlist):
            mlist.Unlock()
            sys.exit(0)

        # Okay, zap them.  Leave them sitting at the list's listinfo page.  We
        # must own the list lock, and we want to make sure the user (BAW: and
        # list admin?) is informed of the removal.
        signal.signal(signal.SIGTERM, sigterm_handler)
        mlist.Lock()
        needapproval = False
        try:
            try:
                mlist.DeleteMember(
                    user, 'via the member options page', userack=1)
            except Errors.MMNeedApproval:
                needapproval = True
            mlist.Save()
        finally:
            mlist.Unlock()
        # Now throw up some results page, with appropriate links.  We can't
        # drop them back into their options page, because that's gone now!
        fqdn_listname = mlist.GetListEmail()
        owneraddr = mlist.GetOwnerEmail()
        url = mlist.GetScriptURL('listinfo', absolute=1)

        title = _('Unsubscription results')
        doc.SetTitle(title)
        doc.AddItem(Header(2, title))
        if needapproval:
            doc.AddItem(_("""Your unsubscription request has been received and
            forwarded on to the list moderators for approval.  You will
            receive notification once the list moderators have made their
            decision."""))
        else:
            doc.AddItem(_("""You have been successfully unsubscribed from the
            mailing list %(fqdn_listname)s.  If you were receiving digest
            deliveries you may get one more digest.  If you have any questions
            about your unsubscription, please contact the list owners at
            %(owneraddr)s."""))
        doc.AddItem(mlist.GetMailmanFooter())
        print doc.Format()
        return
    # Begin dlist addition    
    #  Process overrides of default subscription status.
    if cgidata.has_key('override'):
	subscriber = DlistUtils.Subscriber(mlist)
	override = DlistUtils.Override(mlist)
        thread_reference = cgidata.getvalue('override')
        new_preference_string = cgidata.getvalue('preference')
        subscriber_id = subscriber.getSubscriber_id_raw(user)
        if DEBUG_MODE:
            syslog('info', 'options: subscriber_id = %s, thread_reference = %s, new_preference_string = %s', subscriber_id, thread_reference, new_preference_string)
        try:
            new_preference = int(new_preference_string)
            if subscriber_id and new_preference in [0, 1] and \
                   override.override_from_web(subscriber_id, thread_reference, new_preference):
                if new_preference == 1:
    	            message = 'Done.  You have been subscribed to the conversation.'
                else:
                    message = 'Done.  You have been unsubscribed from the conversation.'
                options_page(mlist, doc, user, cpuser, userlang, message)
                print doc.Format()
                return
        except ValueError:
            # Values of thread_number and preference were not integers
            pass
        message = 'Your request failed.  Make sure you copied the URL correctly.'
        syslog('mischief', 'Bad thread override request (%s, %s, %s)', subscriber_id, thread_reference, new_preference_string)
        options_page(mlist, doc, user, cpuser, userlang, message)
        print doc.Format()
        return
    # End dlist addition

    if cgidata.has_key('options-submit'):
        # Digest action flags
        digestwarn = 0
        cantdigest = 0
        mustdigest = 0

	subscriber = DlistUtils.Subscriber(mlist)
	alias = DlistUtils.Alias(mlist)
        newvals = []
        # First figure out which options have changed.  The item names come
        # from FormatOptionButton() in HTMLFormatter.py
        for item, flag in (('digest',      mm_cfg.Digests),
                           ('mime',        mm_cfg.DisableMime),
                           ('dontreceive', mm_cfg.DontReceiveOwnPosts),
                           ('ackposts',    mm_cfg.AcknowledgePosts),
                           ('disablemail', mm_cfg.DisableDelivery),
                           ('conceal',     mm_cfg.ConcealSubscription),
                           ('remind',      mm_cfg.SuppressPasswordReminder),
                           ('rcvtopic',    mm_cfg.ReceiveNonmatchingTopics),
                           ('nodupes',     mm_cfg.DontReceiveDuplicates),
                           ):
            try:
                newval = int(cgidata.getvalue(item))
            except (TypeError, ValueError):
                newval = None

            # Skip this option if there was a problem or it wasn't changed.
            # Note that delivery status is handled separate from the options
            # flags.
            if newval is None:
                continue
            elif flag == mm_cfg.DisableDelivery:
                status = mlist.getDeliveryStatus(user)
                # Here, newval == 0 means enable, newval == 1 means disable
                if not newval and status <> MemberAdaptor.ENABLED:
                    newval = MemberAdaptor.ENABLED
                    newvals.append((flag, newval))
                    # added to support dlists (2 lines)
                    if DlistUtils.enabled(mlist):
                        subscriber.setDisable(user, 0)

                elif newval and status == MemberAdaptor.ENABLED:
                    newval = MemberAdaptor.BYUSER
                    newvals.append((flag, newval))
                    # added to support dlists (2 lines)
                    if DlistUtils.enabled(mlist):
                        subscriber.setDisable(user, 1)
                    else:
                        continue
            elif newval == mlist.getMemberOption(user, flag):
                continue
            # Should we warn about one more digest?
            if flag == mm_cfg.Digests and \
                   newval == 0 and mlist.getMemberOption(user, flag):
                digestwarn = 1

            newvals.append((flag, newval))
            # Begin added to support dlists
            if DlistUtils.enabled(mlist):

                # Subscriptions to new threads
                newValueOfSubnew = int(cgidata.getvalue('subnew'))
                if newValueOfSubnew != mlist.getMemberOption(user, mm_cfg.SubscribedToNewThreads):
                    subscriber.changePreference(user, newValueOfSubnew)
                    newvals.append((mm_cfg.SubscribedToNewThreads, newValueOfSubnew))

                # Aliases accepted for incoming mail
                aliasString = cgidata.getvalue('aliases')
                # Use commas or spaces as delimiters
                newAliasList = aliasString.replace(',', ' ').split()
                subscriber_id = subscriber.getSubscriber_id_raw(user)
                oldAliasList = alias.get_aliases(subscriber_id)
                if newAliasList != oldAliasList:
                    alias.change_aliases(subscriber_id, oldAliasList, newAliasList)
                 
                # Delivery format
                oldValueOfFormat = subscriber.get_format(subscriber_id)
                newValueOfFormat = int(cgidata.getvalue('format'))
                if newValueOfFormat != oldValueOfFormat:
                    subscriber.changeFormat(user, newValueOfFormat)
            ## End added to support dlists


        # The user language is handled a little differently
        if userlang not in mlist.GetAvailableLanguages():
            newvals.append((SETLANGUAGE, mlist.preferred_language))
        else:
            newvals.append((SETLANGUAGE, userlang))

        # Process user selected topics, but don't make the changes to the
        # MailList object; we must do that down below when the list is
        # locked.
        topicnames = cgidata.getvalue('usertopic')
        if topicnames:
            # Some topics were selected.  topicnames can actually be a string
            # or a list of strings depending on whether more than one topic
            # was selected or not.
            if not isinstance(topicnames, ListType):
                # Assume it was a bare string, so listify it
                topicnames = [topicnames]
            # unquote the topic names
            topicnames = [urllib.unquote_plus(n) for n in topicnames]

        # The standard sigterm handler (see above)
        def sigterm_handler(signum, frame, mlist=mlist):
            mlist.Unlock()
            sys.exit(0)

        # Now, lock the list and perform the changes
        mlist.Lock()
        try:
            signal.signal(signal.SIGTERM, sigterm_handler)
            # `values' is a tuple of flags and the web values
            for flag, newval in newvals:
                # Handle language settings differently
                if flag == SETLANGUAGE:
                    mlist.setMemberLanguage(user, newval)
                # Handle delivery status separately
                elif flag == mm_cfg.DisableDelivery:
                    mlist.setDeliveryStatus(user, newval)
                else:
                    try:
                        mlist.setMemberOption(user, flag, newval)
                    except Errors.CantDigestError:
                        cantdigest = 1
                    except Errors.MustDigestError:
                        mustdigest = 1
            # Set the topics information.
            mlist.setMemberTopics(user, topicnames)
            mlist.Save()
        finally:
            mlist.Unlock()

        # A bag of attributes for the global options
        class Global:
            enable = None
            remind = None
            nodupes = None
            mime = None
            def __nonzero__(self):
                 return len(self.__dict__.keys()) > 0

        globalopts = Global()

        # The enable/disable option and the password remind option may have
        # their global flags sets.
        if cgidata.getvalue('deliver-globally'):
            # Yes, this is inefficient, but the list is so small it shouldn't
            # make much of a difference.
            for flag, newval in newvals:
                if flag == mm_cfg.DisableDelivery:
                    globalopts.enable = newval
                    break

        if cgidata.getvalue('remind-globally'):
            for flag, newval in newvals:
                if flag == mm_cfg.SuppressPasswordReminder:
                    globalopts.remind = newval
                    break

        if cgidata.getvalue('nodupes-globally'):
            for flag, newval in newvals:
                if flag == mm_cfg.DontReceiveDuplicates:
                    globalopts.nodupes = newval
                    break

        if cgidata.getvalue('mime-globally'):
            for flag, newval in newvals:
                if flag == mm_cfg.DisableMime:
                    globalopts.mime = newval
                    break

        # Change options globally, but only if this is the user or site admin,
        # /not/ if this is the list admin.
        if globalopts:
            if not is_user_or_siteadmin:
                doc.addError(_("""The list administrator may not change the
                options for this user's other subscriptions.  However the
                options for this mailing list subscription has been
                changed."""), _('Note: '))
            else:
                for gmlist in lists_of_member(mlist, user):
                    global_options(gmlist, user, globalopts)

        # Now print the results
        if cantdigest:
            msg = _('''The list administrator has disabled digest delivery for
            this list, so your delivery option has not been set.  However your
            other options have been set successfully.''')
        elif mustdigest:
            msg = _('''The list administrator has disabled non-digest delivery
            for this list, so your delivery option has not been set.  However
            your other options have been set successfully.''')
        else:
            msg = _('You have successfully set your options.')

        if digestwarn:
            msg += _('You may get one last digest.')

        options_page(mlist, doc, user, cpuser, userlang, msg)
        print doc.Format()
        return

    if mlist.isMember(user):
        options_page(mlist, doc, user, cpuser, userlang)
    else:
        loginpage(mlist, doc, user, userlang, cgidata)
    print doc.Format()



def options_page(mlist, doc, user, cpuser, userlang, message=''):
    # The bulk of the document will come from the options.html template, which
    # includes it's own html armor (head tags, etc.).  Suppress the head that
    # Document() derived pages get automatically.
    doc.suppress_head = 1

    if mlist.obscure_addresses:
        presentable_user = Utils.ObscureEmail(user, for_text=1)
        if cpuser is not None:
            cpuser = Utils.ObscureEmail(cpuser, for_text=1)
    else:
        presentable_user = user

    fullname = Utils.uncanonstr(mlist.getMemberName(user), userlang)
    if fullname:
        presentable_user += ', %s' % Utils.websafe(fullname)

    # Do replacements
    replacements = mlist.GetStandardReplacements(userlang)
    replacements['<mm-results>'] = Italic(FontAttr(message, size='+2', color='red')).Format() #  Changed by Ellen?
##    replacements['<mm-results>'] = Bold(FontSize('+1', message)).Format() #why is this here? (changed to comment by Robin)
    replacements['<mm-digest-radio-button>'] = mlist.FormatOptionButton(
        mm_cfg.Digests, 1, user)
    replacements['<mm-undigest-radio-button>'] = mlist.FormatOptionButton(
        mm_cfg.Digests, 0, user)

    ## Begin added to support dlists
    if DlistUtils.enabled(mlist):
	subscriber = DlistUtils.Subscriber(mlist)
	alias = DlistUtils.Alias(mlist)
        # Prompt and provide form for changing default subscription status (subscription.preference)
        replacements['<mm-new-threads>'] = """
            <tr><TD BGCOLOR="#cccccc">
            <strong>Subscribed to new conversations?</strong><p>
            If you are subscribed to new conversations, you will receive all messages in a new conversation unless you explicitly unsubscribe.  If you are not subscribed to new conversations, you will only see the first message unless you explicitly subscribe.
            </td><td bgcolor="#cccccc"> """ +  mlist.FormatOptionButton(mm_cfg.SubscribedToNewThreads, 1, user) + "Yes<br>" + mlist.FormatOptionButton(mm_cfg.SubscribedToNewThreads, 0, user) + "No</td></tr>"
        # Aliases for incoming email, added by Systers
        subscriber_id = subscriber.getSubscriber_id_raw_or_die(user)
        oldAliasList = alias.get_aliases(subscriber_id)
        mystring = TextArea('aliases', string.join(oldAliasList, ', '), rows=4, cols=20).Format()
        replacements['<mm-aliases>'] = """
            <tr><TD BGCOLOR="#cccccc">
            <strong>Other incoming email addresses</strong><p>
            If you would like to be able to send messages to the list from email addresses
            other than the one with you subscribed, please specify them here, separated by
            commas.
            </td><td bgcolor="#cccccc">""" + mystring + "</TD></TR>"
        # Prompt and provide form for changing preferred delivery format (subscription.preference)
        choices = [0, 1, 2, 3]  # We don't use choice 0
        for i in [1, 2, 3]:
            choices[i] = '<input type=radio name="format" value=%d' % i
        oldValueOfFormat = subscriber.get_format(subscriber_id)
        choices[oldValueOfFormat] = choices[oldValueOfFormat] + ' CHECKED'
        replacements['<mm-format>'] = '''
            <tr><TD BGCOLOR="#cccccc"> 
            <strong>Email format</strong><p>  
            What format of email messages would you like to receive? 
            If your mail reader can display formatting and hyperlinks 
            (e.g., Outlook, Eudora, or web-based, such as Hotmail,), choose "html". 
            </td><td bgcolor="#cccccc"> %s>html<br> %s>plain text<br> %s>both </td></tr>''' % \
            (choices[2], choices[1], choices[3])

    else:
       # Not strictly necessary but added for robustness
        replacements['<mm-new-threads>'] =  ""
        replacements['<mm-aliases>'] = ""
        replacements['<mm-format>'] = ""
    ## End added to support dlists

    replacements['<mm-plain-digests-button>'] = mlist.FormatOptionButton(
        mm_cfg.DisableMime, 1, user)
    replacements['<mm-mime-digests-button>'] = mlist.FormatOptionButton(
        mm_cfg.DisableMime, 0, user)
    replacements['<mm-global-mime-button>'] = (
        CheckBox('mime-globally', 1, checked=0).Format())
    replacements['<mm-delivery-enable-button>'] = mlist.FormatOptionButton(
        mm_cfg.DisableDelivery, 0, user)
    replacements['<mm-delivery-disable-button>'] = mlist.FormatOptionButton(
        mm_cfg.DisableDelivery, 1, user)
    replacements['<mm-disabled-notice>'] = mlist.FormatDisabledNotice(user)
    replacements['<mm-dont-ack-posts-button>'] = mlist.FormatOptionButton(
        mm_cfg.AcknowledgePosts, 0, user)
    replacements['<mm-ack-posts-button>'] = mlist.FormatOptionButton(
        mm_cfg.AcknowledgePosts, 1, user)
    replacements['<mm-receive-own-mail-button>'] = mlist.FormatOptionButton(
        mm_cfg.DontReceiveOwnPosts, 0, user)
    replacements['<mm-dont-receive-own-mail-button>'] = (
        mlist.FormatOptionButton(mm_cfg.DontReceiveOwnPosts, 1, user))
    replacements['<mm-dont-get-password-reminder-button>'] = (
        mlist.FormatOptionButton(mm_cfg.SuppressPasswordReminder, 1, user))
    replacements['<mm-get-password-reminder-button>'] = (
        mlist.FormatOptionButton(mm_cfg.SuppressPasswordReminder, 0, user))
    replacements['<mm-public-subscription-button>'] = (
        mlist.FormatOptionButton(mm_cfg.ConcealSubscription, 0, user))
    replacements['<mm-hide-subscription-button>'] = mlist.FormatOptionButton(
        mm_cfg.ConcealSubscription, 1, user)
    replacements['<mm-dont-receive-duplicates-button>'] = (
        mlist.FormatOptionButton(mm_cfg.DontReceiveDuplicates, 1, user))
    replacements['<mm-receive-duplicates-button>'] = (
        mlist.FormatOptionButton(mm_cfg.DontReceiveDuplicates, 0, user))
    replacements['<mm-unsubscribe-button>'] = (
        mlist.FormatButton('unsub', _('Unsubscribe')) + '<br>' +
        CheckBox('unsubconfirm', 1, checked=0).Format() +
        _('<em>Yes, I really want to unsubscribe</em>'))
    replacements['<mm-new-pass-box>'] = mlist.FormatSecureBox('newpw')
    replacements['<mm-confirm-pass-box>'] = mlist.FormatSecureBox('confpw')
    replacements['<mm-newcauth-pass-box>'] = mlist.FormatSecureBox('newcauthpw')
    replacements['<mm-confirmcauth-pass-box>'] = mlist.FormatSecureBox('confcauthpw')
    replacements['<mm-change-pass-button>'] = (
        mlist.FormatButton('changepw', _("Change My Password")))
    replacements['<mm-other-subscriptions-submit>'] = (
        mlist.FormatButton('othersubs',
                           _('List my other subscriptions')))
    replacements['<mm-disable-openid-submit>'] = (
        mlist.FormatButton('discauth',
                           _('Disable')))
    replacements['<mm-change-openid-pass>'] = (
        mlist.FormatButton('changeauth',
                           _('Change Common Authentication Password')))
    replacements['<mm-format-option-select>'] = mlist.FormatOptionSelect('listname')
    replacements['<mm-format-option-list>'] = mlist.FormatOptionList()
    replacements['<mm-format-option-end>'] = mlist.FormatOptionEnd()
    replacements['<mm-form-start>'] = (
        mlist.FormatFormStart('client', user))
    replacements['<mm-user>'] = user
    replacements['<mm-presentable-user>'] = presentable_user
    replacements['<mm-email-my-pw>'] = mlist.FormatButton(
        'emailpw', (_('Email My Password To Me')))
    replacements['<mm-umbrella-notice>'] = (
        mlist.FormatUmbrellaNotice(user, _("password")))
    replacements['<mm-logout-button>'] = (
        mlist.FormatButton('logout', _('Log out')))
    replacements['<mm-options-submit-button>'] = mlist.FormatButton(
        'options-submit', _('Submit My Changes'))
    replacements['<mm-global-pw-changes-button>'] = (
        CheckBox('pw-globally', 1, checked=0).Format())
    replacements['<mm-global-deliver-button>'] = (
        CheckBox('deliver-globally', 1, checked=0).Format())
    replacements['<mm-global-remind-button>'] = (
        CheckBox('remind-globally', 1, checked=0).Format())
    replacements['<mm-global-nodupes-button>'] = (
        CheckBox('nodupes-globally', 1, checked=0).Format())

    days = int(mm_cfg.PENDING_REQUEST_LIFE / mm_cfg.days(1))
    if days > 1:
        units = _('days')
    else:
        units = _('day')
    replacements['<mm-pending-days>'] = _('%(days)d %(units)s')

    replacements['<mm-new-address-box>'] = mlist.FormatBox('new-address')
    replacements['<mm-confirm-address-box>'] = mlist.FormatBox(
        'confirm-address')
    replacements['<mm-change-address-button>'] = mlist.FormatButton(
        'change-of-address', _('Change My Address and Name'))
    replacements['<mm-global-change-of-address>'] = CheckBox(
        'changeaddr-globally', 1, checked=0).Format()
    replacements['<mm-fullname-box>'] = mlist.FormatBox(
        'fullname', value=fullname)

    # Create the topics radios.  BAW: what if the list admin deletes a topic,
    # but the user still wants to get that topic message?
    usertopics = mlist.getMemberTopics(user)
    if mlist.topics:
        table = Table(border="0")
        for name, pattern, description, emptyflag in mlist.topics:
            if emptyflag:
                continue
            quotedname = urllib.quote_plus(name)
            details = Link(mlist.GetScriptURL('client') +
                           '/%s/?VARHELP=%s' % (user, quotedname),
                           ' (Details)')
            if name in usertopics:
                checked = 1
            else:
                checked = 0
            table.AddRow([CheckBox('usertopic', quotedname, checked=checked),
                          name + details.Format()])
        topicsfield = table.Format()
    else:
        topicsfield = _('<em>No topics defined</em>')
    replacements['<mm-topics>'] = topicsfield
    replacements['<mm-suppress-nonmatching-topics>'] = (
        mlist.FormatOptionButton(mm_cfg.ReceiveNonmatchingTopics, 0, user))
    replacements['<mm-receive-nonmatching-topics>'] = (
        mlist.FormatOptionButton(mm_cfg.ReceiveNonmatchingTopics, 1, user))

    if cpuser is not None:
        replacements['<mm-case-preserved-user>'] = _('''
You are subscribed to this list with the case-preserved address
<em>%(cpuser)s</em>.''')
    else:
        replacements['<mm-case-preserved-user>'] = ''

    doc.AddItem(mlist.ParseTags('client.html', replacements, userlang))



def loginpage(mlist, doc, user, lang, cgidata=None):
    realname = mlist.real_name
    actionurl = mlist.GetScriptURL('client')
    # Added by Systers to support dlists. Used if someone is trying to unsubscribe from a conversation via the web.
    try:
        override = cgidata.getvalue("override")
        preference = cgidata.getvalue("preference", "0")
        if preference == "":
            preference = "0"  # if there is a mal-formed URL, lets assume they are
                              # trying to unsubscribe -- better than crashing
    except (NameError, AttributeError):
        override = ""
        preference = "0"  # see above
    if user is None:
        title = _('%(realname)s list: member options login page with Common Authentication')
        extra = _('email address and ')
    else:
        safeuser = Utils.websafe(user)
        title = _('%(realname)s list: member options for user %(safeuser)s with Common Authentication')
        obuser = Utils.ObscureEmail(user)
        extra = ''

    
    # Set up the title
    doc.SetTitle(title)
    # We use a subtable here so we can put a language selection box in
    table = Table(width='100%', border=0, cellspacing=4, cellpadding=5)
    # If only one language is enabled for this mailing list, omit the choice
    # buttons.
    table.AddRow([Center(Header(2, title))])
    table.AddCellInfo(table.GetCurrentRowIndex(), 0,
                      bgcolor=mm_cfg.WEB_HEADER_COLOR)
    if len(mlist.GetAvailableLanguages()) > 1:
        langform = Form(actionurl)
        langform.AddItem(SubmitButton('displang-button',
                                      _('View this page in')))
        langform.AddItem(mlist.GetLangSelectBox(lang))
        if user:
            langform.AddItem(Hidden('email', user))      
        table.AddRow([Center(langform)])
    doc.AddItem(table)
    # Preamble
    # Set up the login page
    form = Form(actionurl)
    form.AddItem(Hidden('language', lang))
    table = Table(width='100%', border=0, cellspacing=4, cellpadding=5)
    table.AddRow([_("""In order to change your membership option, you must
    first log in by giving your %(extra)s  common authentication password in the section
    below.  If you don't remember your common authentication password, you can have it
    emailed to you by clicking on the button below.

    <p><strong><em>Important:</em></strong> From this point on, you must have
    cookies enabled in your browser, otherwise none of your changes will take
    effect.
    """)])
    # Password and login button
    ptable = Table(width='50%', border=0, cellspacing=4, cellpadding=5)
    if user is None:
        ptable.AddRow([Label(_('Email address:')),
                       TextBox('email', size=20)])
    else:
        ptable.AddRow([Hidden('email', user)])
        
    ## Begin added to support dlists
    # Check if there's cgi data to carry through in a hidden field
    try:
        if cgidata.has_key('override') and cgidata.has_key('preference'):
            override_info = [Hidden('override', cgidata.getvalue('override')),
                             Hidden('preference', cgidata.getvalue('preference'))]
        else:
            override_info = []
    except NameError:
        override_info = []
    ## End added to support dlists

    ptable.AddRow([Label(_('Password:')), PasswordBox('password', size=20)] + override_info) # Changed by Ellen

    ptable.AddRow([Center(SubmitButton('login', _('Log in')))])
    ptable.AddCellInfo(ptable.GetCurrentRowIndex(), 0, colspan=2)
    table.AddRow([Center(ptable)])    
    conn = psycopg2.connect("dbname=mailman_members user=mailman password=mailman")
    cur = conn.cursor() 
    cur.execute("SELECT address, listname FROM mailman_test WHERE address = '%s' AND openid = 't'" % (user) )
    data = cur.fetchall()
    items = len(data)
    for i in (0,items):
        if data != []:
            title1 = _('OpenID Password Reminder')
       # extra = _('email address and ')
        else:
     #   safeuser = Utils.websafe(user)
            title1 = _('Password Reminder')
     #   obuser = Utils.ObscureEmail(user)
        #extra = ''

    
    table.AddRow([Center(Header(2, title1))])
    table.AddCellInfo(table.GetCurrentRowIndex(), 0,
                      bgcolor=mm_cfg.WEB_HEADER_COLOR)

    table.AddRow([_("""By clicking on the <em>Remind</em> button, your
    password will be emailed to you.""")])

    table.AddRow([Center(SubmitButton('login-remind', _('Remind')))])
    form.AddItem(table)
    doc.AddItem(form)
    doc.AddItem(mlist.GetMailmanFooter())



def lists_of_member(mlist, user):
    hostname = mlist.host_name
    onlists = []
    for listname in Utils.list_names():
        # The current list will always handle things in the mainline
        if listname == mlist.internal_name():
            continue
        glist = MailList.MailList(listname, lock=0)
        if glist.host_name <> hostname:
            continue
        if not glist.isMember(user):
            continue
        onlists.append(glist)
    return onlists



def change_password(mlist, user, newpw, confirmpw):
    # This operation requires the list lock, so let's set up the signal
    # handling so the list lock will get released when the user hits the
    # browser stop button.
    def sigterm_handler(signum, frame, mlist=mlist):
        # Make sure the list gets unlocked...
        mlist.Unlock()
        # ...and ensure we exit, otherwise race conditions could cause us to
        # enter MailList.Save() while we're in the unlocked state, and that
        # could be bad!
        sys.exit(0)

    # Must own the list lock!
    mlist.Lock()
    try:
        # Install the emergency shutdown signal handler
        signal.signal(signal.SIGTERM, sigterm_handler)
        # change the user's password.  The password must already have been
        # compared to the confirmpw and otherwise been vetted for
        # acceptability.
        mlist.setMemberPassword(user, newpw)
        mlist.Save()
    finally:
        mlist.Unlock()



def global_options(mlist, user, globalopts):
    # Is there anything to do?
    for attr in dir(globalopts):
        if attr.startswith('_'):
            continue
        if getattr(globalopts, attr) is not None:
            break
    else:
        return

    def sigterm_handler(signum, frame, mlist=mlist):
        # Make sure the list gets unlocked...
        mlist.Unlock()
        # ...and ensure we exit, otherwise race conditions could cause us to
        # enter MailList.Save() while we're in the unlocked state, and that
        # could be bad!
        sys.exit(0)

    # Must own the list lock!
    mlist.Lock()
    try:
        # Install the emergency shutdown signal handler
        signal.signal(signal.SIGTERM, sigterm_handler)

        if globalopts.enable is not None:
            mlist.setDeliveryStatus(user, globalopts.enable)

        if globalopts.remind is not None:
            mlist.setMemberOption(user, mm_cfg.SuppressPasswordReminder,
                                  globalopts.remind)

        if globalopts.nodupes is not None:
            mlist.setMemberOption(user, mm_cfg.DontReceiveDuplicates,
                                  globalopts.nodupes)

        if globalopts.mime is not None:
            mlist.setMemberOption(user, mm_cfg.DisableMime, globalopts.mime)

        mlist.Save()
    finally:
        mlist.Unlock()



def topic_details(mlist, doc, user, cpuser, userlang, varhelp):
    # Find out which topic the user wants to get details of
    reflist = varhelp.split('/')
    name = None
    topicname = _('<missing>')
    if len(reflist) == 1:
        topicname = urllib.unquote_plus(reflist[0])
        for name, pattern, description, emptyflag in mlist.topics:
            if name == topicname:
                break
        else:
            name = None

    if not name:
        options_page(mlist, doc, user, cpuser, userlang,
                     _('Requested topic is not valid: %(topicname)s'))
        print doc.Format()
        return

    table = Table(border=3, width='100%')
    table.AddRow([Center(Bold(_('Topic filter details')))])
    table.AddCellInfo(table.GetCurrentRowIndex(), 0, colspan=2,
                      bgcolor=mm_cfg.WEB_SUBHEADER_COLOR)
    table.AddRow([Bold(Label(_('Name:'))),
                  Utils.websafe(name)])
    table.AddRow([Bold(Label(_('Pattern (as regexp):'))),
                  '<pre>' + Utils.websafe(pattern) + '</pre>'])
    table.AddRow([Bold(Label(_('Description:'))),
                  Utils.websafe(description)])
    # Make colors look nice
    for row in range(1, 4):
        table.AddCellInfo(row, 0, bgcolor=mm_cfg.WEB_ADMINITEM_COLOR)

    options_page(mlist, doc, user, cpuser, userlang, table.Format())
    print doc.Format()

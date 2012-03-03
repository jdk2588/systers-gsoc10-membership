import os
import cgi
import psycopg2 as pgdb
import psycopg2.extras as pgdbextra
import re
from Mailman import mm_cfg
from Mailman import Utils
from Mailman import MailList
from Mailman import Errors
from Mailman import i18n
from Mailman.htmlformat import *
from Mailman.HTMLFormatter import HTMLFormatter
from Mailman.Logging.Syslog import syslog
from Mailman import DlistUtils  # Added to support dlists

_ = i18n._
i18n.set_language(mm_cfg.DEFAULT_SERVER_LANGUAGE)

def FormatOpenIDLogin():
        return OpenIDForm().Format()
   
def OpenIDForm():
        container = Container()
        container.AddItem(_("Register for the " )
                             +  FormatFormStart('check'))
        container.AddItem(_("Enter address: \n")
                             +  FormatBox('reg-email')
                             +  '<p>')
        container.AddItem(_("Password: \n")
                              + '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
                              + FormatSecureBox('reg-pw')
                              + '<p>')
        out_str = FormatDropDown()
        if out_str == None:
         container.AddItem(_("No list to be choosen from database"))
        else:
         container.AddItem(_("Select list: \n")
                              + '&nbsp; &nbsp;&nbsp;&nbsp;&nbsp;'
                              + FormatOptionStart('listname')
                              + FormatDropDown()
                              + FormatOptionEnd()
                              + FormatHidden('action')
                              + "<p>")
         container.AddItem(SubmitButton('SubscribeOpenID',
                                           _('Register OpenID')))
        container.AddItem("</center>")
        container.AddItem(_('<p>')
                             + FormatFormEnd())
        return container

        

def FormatFormStart(name, extra=''):
     #   base_url = GetScriptURL(name)
     #   if extra:
     #       full_url = "%s/%s" % (base_url, extra)
     #   else:
     #       full_url = base_url
        return ('<FORM Method=POST ACTION="openidreg">' )

def FormatArchiveAnchor():
        return '<a href="%s">' % GetBaseArchiveURL()

def FormatFormEnd():
        return '</FORM>'

def FormatBox(name, size=20, value=''):
        if isinstance(value, str):
            safevalue = Utils.websafe(value)
        else:
            safevalue = value
        return '<INPUT type="Text" name="%s" size="%d" value="%s">' % (
            name, size, safevalue)

def FormatHidden(name, value='display'):
        if isinstance(value, str):
            safevalue = Utils.websafe(value)
        else:
            safevalue = value
        return '<INPUT type="Hidden" name="%s" value="%s">' % (
            name, safevalue)


def FormatOptionStart(listname):
        return '<select name="%s">' % listname 

    
def FormatDropDown():
        conn = pgdb.connect(host='localhost', database='mailman_members', user='mailman', password='mailman')
        cursor = conn.cursor()    
        command = cursor.execute("SELECT listname FROM mailman_test GROUP BY listname HAVING ( count(listname) = 1  OR COUNT(LISTNAME) > 1 );")
        data = cursor.fetchall()
        items = len(data)
        out_str = None
        if data!=[]:   
         while items != 0:
           out_str = ''
           for i in range(0, items):
               out_str +=  "<option> %s </option>" % (data[i][0])
           return out_str
           items = items - 1   
         else:
           return None
def FormatOptionEnd():
        return '</select>'

def FormatSecureBox(name):
        return '<INPUT type="Password" name="%s" size="20">' % name

def FormatButton(name, text='Submit'):
        return '<INPUT type="Submit" name="%s" value="%s">' % (name, text)

def test(list, passwd, id):
    conn = pgdb.connect(host='localhost', database='mailman_members', user='mailman', password='mailman')
    cursor = conn.cursor()   
#    cursor1 = conn.cursor() 
    command = cursor.execute("SELECT listname,address,password = '%s',openid FROM mailman_test ;" % (passwd)) 
    
    data = cursor.fetchall()
    item = len(data)
    for i in range(0, item):
               command = cursor.execute("SELECT listname ,address,openid FROM mailman_test where address = '%s' ;" % (data[i][1])) 
    
               data1 = cursor.fetchall()
               item1 = len(data1)
               for j in range(0, item1):
                while ((id == data1[j][1] and data1[j][2] == True )):
             #  if data1 == True :
		 return "repeat"
              
               while ((list == data[i][0]) and (id == data[i][1]) and (data[i][2] == True)): 
                conn = pgdb.connect(host='localhost', database='mailman_members', user='mailman', password='mailman')
                cursor = conn.cursor()
                cursor.execute("UPDATE mailman_test SET openid='1' WHERE listname = '%s' AND address = '%s'" % (data[i][0], data[i][1]))
                conn.commit()
                return "passed"

def display_page(result):
    print "<HTML>\n"
    print "<HEAD>\n"
    print "\t<TITLE>OpenID Registeration for Systers</TITLE>\n"
    print "</HEAD>\n"
    print "<BODY BGCOLOR = white>\n"
    if (result == "passed"): 
             print "<B> You have Completed the Registeration and now you can use your OpenID\n <B>"
    elif (result == "repeat"):
             print "<B> This email address is already in use , please select a different address\n </B> "
    else:
             print " Please check that you are using correct <B> Username </B>and <B>Password </b>for the<b> List </b> you choose.\n"
    print "</BODY>\n"
    print "</HTML>\n"


def openidreg_overview(lang, msg=''):
    # Present the general listinfo overview
    hostname = Utils.get_domain()
    # Set up the document and assign it the correct language.  The only one we
    # know about at the moment is the server's default.
    doc = Document()
#    doc.set_language(lang)
    doc.set_language(mm_cfg.DEFAULT_SERVER_LANGUAGE)

    legend = _(" OpenID Registeration for Systers Mailing Lists")
    doc.SetTitle(legend)

    table = Table(border=0, width="100%")
    table.AddRow([Center(Header(2, legend))])
    table.AddCellInfo(table.GetCurrentRowIndex(), 0, colspan=2,
                      bgcolor=mm_cfg.WEB_HEADER_COLOR)

    # Skip any mailing lists that isn't advertised.

    if msg:
        greeting = FontAttr(msg, color="ff5060", size="+1")
    else:
        greeting = FontAttr(_('Welcome!'), size='+2')

    welcome = [greeting]
    mailmanlink = Link(mm_cfg.MAILMAN_URL, _('Mailman')).Format()
    

    # set up some local variables
    adj = msg and _('right') or ''
    siteowner = Utils.get_site_email()
    welcome.extend(
        (_(''' This is the Systers OpenID registeration form . To enable your systers account fill in the following entries.
        <p>or Go back to the listinfo page if already using it '''),
         Link(Utils.ScriptURL('listinfo'),
              _('the mailing lists overview page')),
         _(''' <p>If you are having trouble using the lists, please contact '''),
         Link('mailto:' + siteowner, siteowner),
         '.<p>',
         FormatOpenIDLogin(),
         '<p>'))
    
         
    table.AddRow([apply(Container, welcome)])
    table.AddCellInfo(max(table.GetCurrentRowIndex(), 0), 0, colspan=2)

    

    doc.AddItem(table)
    doc.AddItem('<hr>')
    doc.AddItem(MailmanLogo())
    print doc.Format()




def main():
    cgidata = cgi.FieldStorage()
    language = cgidata.getvalue('language')
    parts = Utils.GetPathPieces()
    i18n.set_language(language)
    openidreg_overview(language)   
    if (cgidata.has_key("action") and cgidata.has_key("listname") and cgidata.has_key("reg-pw") and cgidata.has_key("reg-email")):
             if (cgidata["action"].value == "display"):
                result = test(cgidata["listname"].value, cgidata["reg-pw"].value, cgidata["reg-email"].value)
                display_page(result)
    else:
             print "<B> Fields are blank, please enter correct Username , Password and choose your list </B>"
    FormatOpenIDLogin()
    
if __name__ == "__main__":
    main()

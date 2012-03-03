"""Routines supporting the interface with a relational database for dynamic sublists. """
from storm.locals import *
import psycopg2 as pgdb
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import types
import string
import email.Utils
from Mailman.Logging.Syslog import syslog
from Mailman import Errors
from Mailman import ErrorsDlist
from Mailman import mm_cfg
from Mailman.Queue.sbcache import get_switchboard
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from Mailman import Message
from Mailman.ErrorsDlist import *
import urllib
from Mailman.mm_cfg import DEBUG_MODE

lousyThreadNames = ["thread", "subscribe", "unsubscribe", "sub", "unsub", "help", "join", "owner", "admin", 'mailto', 'http', 'bounces', 'leave', 'request', 'new']

#The prime purpose of the decorator function below is to make all class functions using store commands free of the
#repetitive code required in the beg(store = Store(database) for establishing connection with database) and in the end
#(store.commit()for commiting all transactions carried out by the function and then store.close() for closing the connection) 

#"classObject" is a global variable that keeps track of the object that calls its decorated member functions,thus at any instant
#of time whenever decorator function is executed classObject will always represent the value of the object that previously called the decorated function.
classObject = None
#Since the main purpose of the decorator function is to account for the repetitive connection establishing and closing storm commands,there are two main issues that are resolved in the decorator code below:
#1)The case of nested member functions.When one member function A() calls another member function B()inside it.Then both of them 
#refer to same self object,in this case we dont want the decorated function B() to close the self.store connection before A() gets executed.
#So if self ==  classObject(the case of nesting) then only store.commit() should take place.
#2)The case when we declare one object say subscriber = Subscriber(mlist) and then use this subscriber object many times to
#call different decorated member functions of Subscriber class.Such kind of case will always satisfy self ==  classObject,
#here we want store.close() to take place as if it does not,it will leave the store connection always open that can possibly be a bug.

def decfunc(f):
    def inner(self, *args):
        global classObject
        if self == classObject:
            if self.store == None:#for the case when same object is used for calling more than one functions
                self.store = Store(self.database)
                result = f(self, *args)
                self.store.commit()
                self.store.close()
                self.store = None
            else:#To handle the nesting issue
                result = f(self, *args)
                self.store.commit()
        else:#for the case whenever a new object calls its decorated member function
            classObject = self
            self.store = Store(self.database)
            result = f(self, *args)
            self.store.commit()
            self.store.close()
            self.store = None
        return result
    return inner

#Define all the classes corresponding to the tables in the database
class Subscriber(object):
    __storm_table__ = "subscriber"
    subscriber_id = Int(primary = True, default = AutoReload)
    mailman_key = Unicode()
    preference = Int(default = 1)
    format = Int(default = 3)
    deleted = Bool(default = False)
    suppress = Int(default = 0)

    def __init__(self, mlist):
        self.mlist = mlist
        self.database = getConn(mlist)

    @decfunc
    def getSubscriber_id_raw(self, addr):
        if addr == None:
            return None

        command = "result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(addr.lower(),'utf-8'))\na = [(subscriber.subscriber_id) for subscriber in result]\n"
        if DEBUG_MODE:
            syslog('info', "DlistUtils:(getSubscriber_id_raw)executing query:\n%s", command)
        #storm recognizes unicode only
        result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(addr,"utf-8")) 
        a = [(subscriber.subscriber_id) for subscriber in result]
        if DEBUG_MODE:
            syslog('info', 'value of a is: %s\n', a)

        #The ResultSet "a" obtained in above storm command and later on in similar ones is always a list
        if a == []:
            return None 
        else:
            return a[0]

    def getSubscriber_id_raw_or_die(self, addr):
        result = self.getSubscriber_id_raw(addr)
        if (result == None):
            #syslog('error', 'getSubscriber_id_raw_or_die /msg nickserv register <your-password> <your-email>unable to find address /%s/ for mailing list /%s/', addr, self.mlist.internal_name())
            raise ErrorsDlist.InternalError
        else:
            return result

    def getSubscriber_id(self, msg, msgdata, safe=0, loose=0):
        """Returns the subscriber_id of the sender of a message and sets the 'subscriber_id' field in the msg object."""
        fromAddr = email.Utils.parseaddr(msg['From'])[1]
        try:
            subscriber_id = msgdata['subscriber_id']
            return subscriber_id
        except:
            subscriber_id = self.getSubscriber_id_raw(fromAddr)
            if subscriber_id == None:
                alias = Alias(self.mlist)
                bestAddr = alias.canonicalize_sender(msg.get_senders())
                subscriber_id = self.getSubscriber_id_raw(bestAddr)
                if subscriber_id == None:
                    #if DEBUG_MODE:
                        #syslog('info', "DlistUtils.getSubscriber_id: subscriber_id is None and safe is %d", safe)
                    if safe:
                        # This could happen if a non-member is given permission to post
                        return 0
                    else:
                        #if DEBUG_MODE:
                            #syslog('info', "Raising ErrorsDlist.NotMemberError")
                        raise ErrorsDlist.NotMemberError("Your request could not be processed because %s is not subscribed to %s.  Perhaps you are subscribed with a different email address, which forwards to %s.  If so, please log into %s and add this as an 'other incoming email address'." % (fromAddr, self.mlist.internal_name(), fromAddr, self.mlist.GetScriptURL('options', 1))) 
            if DEBUG_MODE:
                syslog('info', 'subscriber_id = %d\n', subscriber_id)
            msgdata['subscriber_id'] = subscriber_id
            return subscriber_id

    @decfunc
    def get_format(self, subscriber_id):
        command = "return int(self.store.get(Subscriber,subscriber_id).format)\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(get_format):Executing query:\n%s', command)
        return int(self.store.get(Subscriber,subscriber_id).format)    

    @decfunc
    def setDisable(self, member, flag):
        """Disable/enable delivery based on mm_cfg.DisableDelivery"""
        command = "result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,'utf-8'))\noldval = [(subscriber.suppress) for subscriber in result]\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(setDisable):Executing query:\n%s\n Member whose suppress value is to be found \n %s', command, member)
        result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,"utf-8"))
        oldval = [(subscriber.suppress) for subscriber in result]
	if oldval == []:
	    if DEBUG_MODE:
	        syslog('info','oldval is an empty list.\nThis can happen either because of\n 1)Permission issues (Do a: bin/check_perms)\n 2)Inconsistency between database and pickle files (A user is in the database but not in pickle files or vice versa,Do a bin/find_problems.py)')
        oldval = oldval[0]
	if DEBUG_MODE:
            syslog('info','the value of oldval is %s:', oldval)

        if flag:
            newval = oldval | 1          # Disable delivery
        else:
            newval = oldval & ~1          # Enable delivery
        if DEBUG_MODE:
            syslog('info','the value of newval is %s:', newval)
        command = "self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,'utf-8')).set(suppress = newval)\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(setDisable):Executing query:\n%s', command)
        self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,"utf-8")).set(suppress = newval)       

    @decfunc
    def setDigest(self, member, flag):
        """Disable/enable delivery based on user digest status"""

        command = "result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,'utf-8'))\noldval = [(subscriber.suppress) for subscriber in result]\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(setDigest):Executing query:\n%s', command)
        result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,"utf-8"))
        oldval = [(subscriber.suppress) for subscriber in result]
	if oldval == []:
	    if DEBUG_MODE:
	        syslog('info','oldval is an empty list.\nThis can happen either because of\n 1)permission issues (Do a: bin/check_perms)\n 2)Inconsistency between database and pickle files (A user is in the database but not in pickle files or vice versa,Do a bin/find_problems.py)')
        oldval = oldval[0]
        if DEBUG_MODE:
            syslog('info','value of oldval %s:', oldval)

        if flag:
            newval = oldval | 2          # Suppress delivery (in favor of digests)
        else:
            newval = oldval & ~2          # Enable delivery (instead of digests)

        command = "self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,'utf-8')).set(suppress = newval)\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(setDigest):Executing query:\n%s', command)
        self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,"utf-8")).set(suppress = newval)

    @decfunc
    def changePreference(self, member, preference):
        """Change a user's default preference for new threads."""
        command = "self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,'utf-8')).set(preference = preference)\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(changePreference):Executing query:\n%s', command)    
        self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,"utf-8")).set(preference = preference)

    @decfunc
    def changeFormat(self, member, format):
        """Change a user's preferred delivery format (plain text and/or html)"""
        command = "self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,'utf-8')).set(format = format)\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(changeFormat):Executing query:\n%s', command)
        self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(member,"utf-8")).set(format = format)    

    ### We have to watch out for a tricky case (that actually happened):
    ### User foo@bar.com changes her address to something already in the
    ### subscriber database (possibly deleted).
    @decfunc
    def changeAddress(self, oldaddr, newaddr):
        """Change email address in SQL database"""
        if DEBUG_MODE:
        	syslog('info', "Changing email address on %s from '%s' to '%s'", self.mlist.internal_name(), oldaddr, newaddr)
        ## Check if newaddr is in sql database        
        num_matches = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(newaddr.lower(),"utf-8")).count()

        if num_matches > 1:
            syslog('error', 'Multiple users with same key (%s): %s', self.mlist.internal_name(), newaddr)
            return
        if num_matches == 1:
            self.mergeSubscribers(oldaddr, newaddr)

        command = "num_matches = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(newaddr,'utf-8')).count()\nself.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(oldaddr,'utf-8')).set(mailman_key = unicode(newaddr,'utf-8'))\nself.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(newaddr.lower(),'utf-8')).set(deleted = False)\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(changeAddress):Executing query:\n%s', command)
        self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(oldaddr,"utf-8")).set(mailman_key = unicode(newaddr,"utf-8")) 
        self.store.commit()            
        self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(newaddr.lower(),"utf-8")).set(deleted = False)

    @decfunc
    def unsubscribeFromList(self, key):
        """Indicate that a user has unsubscribed by setting the deleted flag in the subscriber table."""

        command = "self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key,'utf-8')).set(deleted = True)\nself.store.find(Alias,Alias.subscriber_id == subscriber_id).remove()\n"
        if DEBUG_MODE:
            syslog('info', 'DlisUtils(unsubscribeFromList):Executing query:\n%s', command)          
        self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key,"utf-8")).set(deleted = True)
        # get the subscriber id from the mailman_key & delete all aliases  
        subscriber_id = self.getSubscriber_id_raw(key)

        if subscriber_id == None:
            syslog('error', "DlistUtils.unsubscribeFromList called with '%s', but it can't be found in the SQL database", key)
        else:            
            self.store.find(Alias,Alias.subscriber_id == subscriber_id).remove()

    @decfunc
    def subscribeToList(self, key):
        """Add a member to the subscriber database, or change the record from deleted if it was already present."""

        command = "count = (self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key.lower(),'utf-8'))).count()\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils(subscribeToList):Executing query:\n%s', command)
        # First see if member is subscribed with deleted field = false
        count = (self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key.lower(),"utf-8"))).count()

        if count:
            command = "self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key.lower(),'utf-8')).set(deleted = False)"
            if DEBUG_MODE:
                syslog('info', 'DlistUtils(subscribeToList):Executing query:\n%s', command)
            self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key.lower(),"utf-8")).set(deleted = False)

	    result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key.lower(),"utf-8"))
            Email = [(subscriber.mailman_key) for subscriber in result]
	    Email = Email[0]
	    if Email != key: #That is if one was in lowercase and other in uppercase then update mailman_key with case sensitivity same as key
		self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(key.lower(),"utf-8")).set(mailman_key = unicode(key,"utf-8"))
	    
        else:
            # format is text-only (1) by default
            command = "subscriber = self.store.add(Subscriber())\nmailman_key = unicode(key,'utf-8')\npreference = 1\ndeleted = False\nformat = 1\nsuppress = 0"
            if DEBUG_MODE:
                syslog('info', 'DlistUtils(subscribeToList)Executing query:\n%s', command)
            self.mailman_key = unicode(key,"utf-8")
            self.preference = 1
            self.deleted = False
            self.format = 1
            self.suppress = 0
            self.store.add(self)

    @decfunc
    def mergeSubscribers(self, oldaddr, newaddr):
        # use the original subscriber id as the ID going forward
        if DEBUG_MODE:
            syslog('info', 'Executing commands of mergeSubscribers:')
        result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(oldaddr,"utf-8"))
        new_id = [(subscriber.subscriber_id) for subscriber in result]
        new_id = new_id[0]
        if DEBUG_MODE:
            syslog('info', 'the value of new_id: %s', new_id)
        result = self.store.find(Subscriber,Subscriber.mailman_key.lower() == unicode(newaddr.lower(),"utf-8"))
        obsolete_id = [(subscriber.subscriber_id) for subscriber in result]
        obsolete_id = obsolete_id[0]    
        if DEBUG_MODE:
            syslog('info', 'the value of obsolete_id: %s', obsolete_id)
 
        self.store.find(Message,Message.sender_id == obsolete_id).set(sender_id = new_id)
        self.store.find(Override,Override.subscriber_id == obsolete_id).set(subscriber_id = new_id)
        self.store.find(Alias,Alias.subscriber_id == obsolete_id).set(subscriber_id = new_id)
        self.store.find(Subscriber,Subscriber.subscriber_id == obsolete_id).remove()    

class Message(object):
    __storm_table__ = "message"
    message_id = Int(primary = True, default = AutoReload)
    sender_id = Int()
    subscriber = Reference(sender_id, Subscriber.subscriber_id)
    subject = Unicode()
    thread_id = Int()

    def __init__(self, mlist):
        self.mlist = mlist
        self.database = getConn(mlist)

    @decfunc
    def createMessage(self, msg, msgdata):
        """Create a new message (in the database), returning its id."""
        subscriber = Subscriber(self.mlist)
        senderID = subscriber.getSubscriber_id(msg, msgdata, safe=1, loose=1)
        # extract subject and escape quotes
        subject = msg['Subject'].encode().replace("'", "''")
        try:
            threadID = msgdata['thread_id']
        except:
            threadID = -1
        command = "message = self.store.add(Message())\nmessage.sender_id = senderID\nmessage.thread_id = threadID\nmessage.subject = unicode(subject,'utf-8')\nmessageID = self.store.find(Message).max(Message.message_id)\n"
        if DEBUG_MODE:
            syslog('info','DlistUtils:(createMessage)executing query:\n%s', command)
        #message_id has autoreload set,its value will be serially updated in database 
        self.sender_id = senderID
        self.thread_id = threadID
        self.subject = unicode(subject,"utf-8") 
        self.store.add(self) 
        messageID = self.store.find(Message).max(Message.message_id)     
        if DEBUG_MODE:
            syslog('info','Result of query(messageID) is: %s\n', messageID)
        return messageID

class Thread(object):
    __storm_table__ = "thread"
    thread_id = Int(primary = True, default = AutoReload)
    thread_name = Unicode()
    base_message_id = Int()
    message = Reference(base_message_id, Message.message_id)
    status = Int(default = 0)
    parent = Int()

    def __init__(self, mlist):
        self.mlist = mlist
        self.database = getConn(mlist)

    @decfunc
    def createThread(self, msg, msgdata, threadBase):
        """Create a new thread, returning its unique id, name."""
        message = Message(self.mlist)
        subscriber = Subscriber(self.mlist) 
        msgdata['message_id'] = message.createMessage(msg, msgdata)
        senderID = subscriber.getSubscriber_id(msg, msgdata, safe=1, loose=1)
        command = "thread = self.store.add(Thread())\nthread.base_message_id = msgdata['message_id']\nthreadID = self.store.find(Thread).max(Thread.thread_id)\nself.store.find(Message,Message.message_id == msgdata['message_id']).set(thread_id = threadID)\n"
        if DEBUG_MODE:
            syslog('info','DlistUtils:(createThread)executing query:\n%s', command)
        self.base_message_id = msgdata['message_id']
        self.store.add(self)
        threadID = self.store.find(Thread).max(Thread.thread_id)          
        self.store.find(Message,Message.message_id == msgdata['message_id']).set(thread_id = threadID)

        ## Choose a unique name for the thread
        # Try to get the name from the to-line, e.g., listname+new+name@hostname
        if threadBase:
            threadBase = self.alphanumericOnly(threadBase).lower()
            if threadBase in lousyThreadNames or not len(threadBase):
                threadBase = None

        # If a name wasn't explicitly specified, try to get one from the subject
        if not threadBase:
            # No thread name was specified -- try to get from subject line.
            # If none in subject line, the threadID will be returned
            threadBase = self.subjectToName(msg['Subject'].encode(), threadID)

        # Make sure the thread can fit in the field (char(16))
        threadBase = threadBase[:13]
        command = "num = self.store.find(Thread,Thread.thread_name == unicode(threadBase,'utf-8')).count()\nself.store.find(Thread,Thread.thread_id == threadID).set(thread_name = threadName)\n"
        if DEBUG_MODE:
            syslog('info','DlistUtils:(createThread)executing query:\n%s', command)
        # If the threadBase is not unique, make threadBase unique by appending a number
        num = self.store.find(Thread,Thread.thread_name.like(unicode(threadBase + "%","utf-8"))).count()
        if not num:
            threadName = unicode(threadBase,"utf-8")
        else:
            threadName = unicode(threadBase + str(num+1),"utf-8" )

        self.store.find(Thread,Thread.thread_id == threadID).set(thread_name = threadName)

        return (threadID, threadName.encode("utf-8"))

    def email_recipients(self, msg, msgdata, lists, pref):
        """Finding the email addresses of matching subscribers from lists,and using the list info to email everyone"""
        returnList = GetEmailAddresses(self.mlist, lists)    
        if DEBUG_MODE:
            syslog('info', 'email sent to: [%s]', returnList)
                
        msgdata['recips'] = returnList
        self.setFooterText(msg, msgdata, pref)
        dq = get_switchboard(mm_cfg.DLISTQUEUE_DIR)
        dq.enqueue(msg, msgdata, listname=self.mlist.internal_name())

    @decfunc
    def newThread(self, msg, msgdata, threadBase=None):
        """Starts a new thread, including creating and enqueueing the initial messages"""
        id, name = self.createThread(msg, msgdata, threadBase)
        msgdata['thread_id'] = id
        msgdata['thread_name'] = name

        # Delete any other 'To' headings
        del msg['To']
        msg['To'] =  '%s+%s@%s' % (self.mlist.internal_name(),
                             	   name,
                             	   self.mlist.host_name)    
        for i in (1, 2):
            # different footers for different prefs, so we need to queue separately
            if(i==1):
                #For condition where preference = True
                pref=True
                if DEBUG_MODE:
                    syslog('info', 'DlistUtils:(newThread)executing query:\nfor pref = true\n\n')
            if(i==2):
                #For condition where preference = False
                pref=False
                if DEBUG_MODE:
                    syslog('info', 'DlistUtils:(newThread)executing query:\nfor pref = false\n\n')

            #Execute a SELECT statement, to find the list of matching subscribers.
            result_new_sql = self.store.find(Subscriber,And(Subscriber.preference == pref,Subscriber.deleted == False,Subscriber.suppress == 0))
            lists = [(subscriber.mailman_key.encode('utf-8')) for subscriber in result_new_sql]
            if DEBUG_MODE:
                syslog('info','value of lists: %s\n', lists)
            self.email_recipients(msg, msgdata, lists, pref)

        # Make original message go to nobody (but be archived)
        msgdata['recips'] = []

    @decfunc
    def continueThread(self, msg, msgdata, threadReference):
        """Continue an existing thread, no return value."""
        subscriber = Subscriber(self.mlist)
        message = Message(self.mlist)
        senderID = subscriber.getSubscriber_id(msg, msgdata, safe=1, loose=1)
        msgdata['message_id'] = message.createMessage(msg, msgdata)

        pref=True

        # email selected people
        #Execute a SELECT statement, to find the list of matching subscribers.
        command = "lists = [(subscriber.mailman_key.encode('utf-8')) for subscriber in result_continue_sql]\n"
        if DEBUG_MODE:
            syslog('info', 'DlistUtils:(continueThread) executing query:\n%s', command)

        # these people get the email by default
        result = self.store.find(Subscriber,And(Subscriber.deleted == False, Subscriber.suppress == 0, Subscriber.preference == 1))
        email_keys = set(subscriber.mailman_key.encode('utf-8') for subscriber in result)

        # these people get the mail, because they overrode their preference for this thread
        result = self.store.find((Subscriber,Override),And(Override.subscriber_id == Subscriber.subscriber_id, Subscriber.suppress == 0, Override.thread_id == msgdata['thread_id'],Override.preference == 1))
        yes_email_keys = set(subscriber.mailman_key.encode('utf-8') for (subscriber,override) in result)

        # these people don't get the mail, due to override
        result = self.store.find((Subscriber,Override),And(Override.subscriber_id == Subscriber.subscriber_id, Override.thread_id == msgdata['thread_id'],Override.preference == 0))
        no_email_keys = set(subscriber.mailman_key.encode('utf-8') for (subscriber,override) in result)

        email_keys.update(yes_email_keys)
        email_keys.difference_update(no_email_keys)

        self.email_recipients(msg, msgdata, email_keys, pref)

        # Make original message go to nobody (but be archived)
        msgdata['recips'] = []

    @decfunc
    def threadIDandName(self, threadReference):
        """Given thread_id or thread_name, determine the other, returning (thread_id, thread_name)"""    
        try:
            thread_id = int(thread_reference)
            try:
                command = "result = self.store.find(Thread,Thread.thread_id == thread_id)\nthread_name = [(thread.thread_name) for thread in result]\nthread_name = thread_name.encode('utf-8')\n"
                if DEBUG_MODE:
                    syslog('info', 'DlistUtils(threadIDandName)Executing query:\n%s', command)
                result = self.store.find(Thread,Thread.thread_id == thread_id)
                thread_name = [(thread.thread_name) for thread in result]
                thread_name = thread_name.encode('utf-8')            
            except:
                raise NonexistentThreadRequest("Your message could not be sent because you specified a nonexistent conversation (%d).  Perhaps you meant to start a new conversation, which you can do by addressing your message to %s+new@%s" % (thread_id, self.mlist.real_name, self.mlist.host_name))
        except:
            thread_name = threadReference.lower()
            if DEBUG_MODE:
                syslog('info', 'thread_name = %s\n', thread_name)
            command = "result = self.store.find(Thread,Thread.thread_name == unicode(thread_name,'utf-8'))\nthread_id = [(thread.thread_id) for thread in result]\n"
            if DEBUG_MODE:
                syslog('info', 'DlistUtils(threadIDandName)Executing query:\n%s', command)
            result = self.store.find(Thread,Thread.thread_name == unicode(thread_name,'utf-8'))
            thread_id = [(thread.thread_id) for thread in result]
            if not thread_id:
                raise NonexistentThreadRequest("Your message could not be sent because you addressed it to a nonexistent conversation (%s).  Perhaps you meant to start a new conversation named %s, which you can do by addressing your message to %s+new+%s@%s" % (thread_name, thread_name, self.mlist.real_name, thread_name, self.mlist.host_name))

            # result was a list (since theoretically >1 result could have been returned from the db.)
            # we just want the one result.
            thread_id = thread_id[0]
            if DEBUG_MODE:
                syslog('info', 'thread_id: %s\n', thread_id)            

        return (thread_id, thread_name)

    def getThreadAddress(msgdata):
        """The list address for any given thread."""
        return "%s+%s@%s" % (self.mlist.internal_name(), msgdata['thread_name'], self.mlist.host_name)

    def subscribeToThread(self, msg, msgdata):
        """Subscribe the sender of a message to a given thread."""
        override = Override(self.mlist)
        override.override(msg, msgdata, 1)

    def unsubscribeFromThread(self, msg, msgdata):
        """Unubscribe the sender of a message from a given thread."""
        override = Override(self.mlist)
        override.override(msg, msgdata, 0)

    def alphanumericOnly(self, s):
        """Filter any non-letter characters from a string"""
        result = [letter for letter in s if letter in string.ascii_letters or letter in string.digits]
        return string.join(result, '')

    def subjectToName(self, subject, threadID):
        """Return a lower-case name for a new thread based on the subject, if present, or on the threadID"""
        result = None

        if subject == '':
            return str(threadID)

        subjectWords = [self.alphanumericOnly(w) for w in subject.split()]

        # Choose the longest word of 4 or more characters
        maxLength = 3
        maxWord = None
        for word in subjectWords:
            if len(word) > maxLength and word not in lousyThreadNames:
                maxWord = word
                maxLength = len(word)
            if maxWord:
                result = maxWord.lower()

            if not result:
                # Choose the first word that's not a stop word or lousy thread name
                stopWords = ["a", "an", "the", "of", "re", "you", "i", "no", "not", "do", "for"]
                for word in subjectWords:
                    if word not in stopWords and word not in lousyThreadNames:
                        result = word.lower()
                        break

            if not result:
                # If no other candidate, just return the first subject word
                result = subjectWords[0].lower() + str(threadID)

        return result[:12]

    def setFooterText(self, msg, msgdata, preference):
        msgdata['dlists_preference'] = preference
        thread_name = msgdata['thread_name']
        thread_id = msgdata['thread_id']
        override = Override(self.mlist)
        web_addr = override.overrideURL(self.mlist.internal_name(), self.mlist.host_name, thread_id, not preference)
        if preference == 1:
            subscribe_string = "unsubscribe"
            preposition = "from"
        else:
            subscribe_string = "subscribe"
            preposition = "to"
        email_addr = '%s+%s+%s@%s' % (self.mlist.internal_name(), thread_name, subscribe_string, self.mlist.host_name)
        #if DEBUG_MODE:
            #syslog('info', "msg['Subject'] = /%s/", msg['Subject'])
        subject = urllib.quote(msg['Subject'].encode())
        post_addr = "%s+%s@%s" % (self.mlist.internal_name(), thread_name, self.mlist.host_name)
        post_addr_with_subject = "%s?Subject=%s" % (post_addr, subject)
        #if DEBUG_MODE:
            #syslog('info', 'post_addr_with_subject = %s', post_addr)

        # Used in Handlers/ToDigest.py
        msgdata['contribute'] = "To contribute to this conversation, send " \
                        "your message to <%s+%s@%s>\n" % \
                        (self.mlist.internal_name(), msgdata['thread_name'], self.mlist.host_name)

        # Used in ToArchive
        msgdata['contribute-html'] = 'To contribute to this conversation, send your message to <a href="mailto:%s">%s</a>\n' % (post_addr, post_addr)
        msgdata['footer-text'] = '\n\nTo %s %s this conversation, send email to <%s> or visit <%s>\nTo contribute to this conversation, use your mailer\'s reply-all or reply-group command or send your message to %s\nTo start a new conversation, send email to <%s+new@%s>\nTo unsubscribe entirely from %s, send email to <%s-request@%s> with subject unsubscribe.' % (subscribe_string, preposition, email_addr, web_addr, post_addr, self.mlist.internal_name(), self.mlist.host_name, self.mlist.internal_name(), self.mlist.internal_name(), self.mlist.host_name)
        #if DEBUG_MODE:
            #syslog('info', 'footer-text = /%s/', msgdata['footer-text'])
        msgdata['footer-html'] = '<br>To %s %s this conversation, send email to <a href="mailto:%s">%s</a> or visit <a href="%s">%s</a>.<br>To contribute to this conversation, use your mailer\'s reply-all or reply-group command or send your message to <a href="mailto:%s?subject=%s">%s</a>.<br>To start a new conversation, send email to <a href="mailto:%s+new@%s">%s+new@%s</a><br>To unsubscribe entirely from %s, send mail to <a href="mailto:%s-request@%s?subject=unsubscribe">%s-request@%s</a> with subject unsubscribe.' % (subscribe_string, preposition, email_addr, email_addr, web_addr, web_addr, post_addr, subject, post_addr, self.mlist.internal_name(), self.mlist.host_name, self.mlist.internal_name(), self.mlist.host_name, self.mlist.internal_name(), self.mlist.internal_name(), self.mlist.host_name, self.mlist.internal_name(), self.mlist.host_name)

class Alias(object):
    __storm_table__ = "alias"    
    pseudonym = Unicode(primary = True)
    subscriber_id = Int()
    subscriber = Reference(subscriber_id, Subscriber.subscriber_id)

    def __init__(self, mlist):
        self.mlist = mlist
        self.database = getConn(mlist)

    @decfunc
    def canonicalize_sender(self, aliases):
        """Execute a SELECT statement, returning the email addresses of matching subscribers."""

        command = "result = self.store.find((Subscriber,Alias),Alias.pseudonym = alias,Subscriber.subscriber_id = Alias.subscriber_id)\nlists = [(subscriber.mailman_key) for subscriber,alias in result]\n"
        if DEBUG_MODE:
             syslog('info', 'DlistUtils(canonicalize_sender)Executing query:\n%s', command)

        for alias in aliases:
            if DEBUG_MODE:
                syslog('info', 'Checking if <%s> is an alias', alias)
            result = self.store.find((Subscriber,Alias),And(Alias.pseudonym == unicode(alias,'utf-8'),Subscriber.subscriber_id == Alias.subscriber_id))
            lists = [(subscriber.mailman_key.encode('utf-8')) for (subscriber,alias) in result]

            returnList = GetEmailAddresses(self.mlist, lists)        
            match = returnList

            if len(match) == 1:
                # I should really confirm that there is only one match
                #if DEBUG_MODE:
                    #syslog('info', 'Match: %s', match)
                if DEBUG_MODE:
                    syslog('info', 'Match found: <%s>', match[0])
                return match[0]
            elif len(match) > 1:
                raise DatabaseIntegrityError

    @decfunc
    def get_aliases(self, subscriber_id):
        """Execute a SELECT statement, returning the results as a list."""
        command = "result = self.store.find(Alias,Alias.subscriber_id == subscriber_id)\nlists = [(alias.pseudonym.encode('utf-8')) for alias in result]\n"
        if DEBUG_MODE:
             syslog('info', 'DlistUtils(get_aliases):Executing query:\n%s', command)
        if DEBUG_MODE:
             syslog('info', 'The value of subscriber_id is: %s\n', subscriber_id)
        result = self.store.find(Alias,Alias.subscriber_id == subscriber_id)
        lists = [(alias.pseudonym.encode('utf-8')) for alias in result]

        return lists

    @decfunc
    def change_aliases(self, subscriber_id, oldAliasList, newAliasList):
        if DEBUG_MODE:
             syslog('info', 'executing change_aliases\n')
        for a in oldAliasList:
            if a not in newAliasList:
                self.store.find(Alias,Alias.pseudonym == unicode(a,"utf-8")).remove()
        for a in newAliasList:
            if a not in oldAliasList:
		syslog('info', 'going to add alias in database\n')
                self.pseudonym = unicode(a,"utf-8")
                self.subscriber_id = subscriber_id
                self.store.add(self)
		syslog('info', 'alias added\n')

class Override(object):
    __storm_table__ = "override"
    __storm_primary__ = "subscriber_id", "thread_id"
    subscriber_id = Int()
    subscriber = Reference(subscriber_id, Subscriber.subscriber_id)
    thread_id = Int()
    thread = Reference(thread_id, Thread.thread_id)
    preference = Int()

    def __init__(self, mlist):
        self.mlist = mlist
        self.database = getConn(mlist)

    def override(self, msg, msgdata, preference):
        """Subscribe or unsubscribe a user from a given thread."""
        if DEBUG_MODE:
             syslog('info', 'DlistUtils: in override')
        subscriber = Subscriber(self.mlist)
        subscriberID = subscriber.getSubscriber_id(msg, msgdata, loose=1) 
        threadID = msgdata['thread_id']
        self._override_inner(subscriberID, threadID, preference)

    def override_from_web(self, subscriberID, thread_reference, preference):
        """Add an override entry to the database, returning false if unable to fulfil request"""
        try:
            threadNum = int(thread_reference)
            preference = int(preference)
        except ValueError:
            thread = Thread(self.mlist)
            threadNum, temp =thread.threadIDandName(thread_reference)
        return self._override_inner(subscriberID, threadNum, preference)

    # This is called both by override and override_from_web, above
    @decfunc
    def _override_inner(self, subscriberID, threadID, preference):
        """Add an override entry to the database, returning false if unable to fulfil request"""

        #if DEBUG_MODE:
             #syslog('info', 'DlistUtils: in override_inner')
        #First check if thread exists    
        command = "exists = self.store.find(Thread,Thread.thread_id == threadID).count()\nself.store.find(Override,And(Override.subscriber_id == subscriberID,Override.thread_id == threadID)).remove()\noverride = self.store.add(Override())\noverride.subscriber_id = subscriberID\noverride.thread_id = threadID\noverride.preference = preference\n"
        if DEBUG_MODE:
             syslog('info', 'DlistUtils(override_from_web):Executing query:\n%s', command)
        exists = self.store.find(Thread,Thread.thread_id == threadID).count()        

        if not exists:
            return 0

        # Remove any prior override by this user
        self.store.find(Override,And(Override.subscriber_id == subscriberID,Override.thread_id == threadID)).remove()

        # Now, insert the change
        self.subscriber_id = subscriberID    
        self.thread_id = threadID
        self.preference = preference
        self.store.add(self)        

        return 1

    def overrideURL(self, list_name, host_name, thread_reference, preference):
        return 'http://%s/mailman/options/%s?override=%s&preference=%d' % (host_name, list_name, thread_reference, preference)

#Functions Independent of the database tables in DlistUtils

def GetEmailAddresses(mlist, subscribers):
    """Extract email addresses from list of matching subscribers"""
    returnList = []

    for s in subscribers:
        try:
            newMember = mlist.getMemberCPAddress(s)
            returnList.append(newMember)
        except:
            syslog('error', 'Unable to find user ' + s + ' in internal database for %s', mlist.internal_name())
           
        #if DEBUG_MODE:
         #    syslog('info', 'Result is: %s', returnList)
    return returnList

def enabled(mlist):
    """Check whether a given mailing list has dynamic sublists enabled"""
    try:
        return mlist.dlists_enabled  
    except:
        return 0

def getConn(mlist):
    """Return a connection to the database for a given mailing list.The argument may be either the mlist object or a string."""
    if not mlist:
        uri = mm_cfg.STORM_DB + '://' + mm_cfg.STORM_DB_USER + ':' + mm_cfg.STORM_DB_PASS + '@' + mm_cfg.STORM_DB_HOST + '/' +  mm_cfg.STORM_DB
        return create_database(uri)

    try:
        name = mlist.internal_name()
    except:
        name = mlist.lower()
    uri = mm_cfg.STORM_DB + '://' + mm_cfg.STORM_DB_USER + ':' + mm_cfg.STORM_DB_PASS + '@' + mm_cfg.STORM_DB_HOST + '/' + name
    return create_database(uri)

def _create_database(name):
    """Create a database. This requires us to not be in a transaction."""
    conn = pgdb.connect(host='localhost', database='postgres', user='mailman', password='mailman')
    old_iso_lvl = conn.isolation_level
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    cursor.execute('create database "%s"' % name) 
    conn.set_isolation_level(old_iso_lvl)

def _remove_database(name):
    """Remove a database. This requires us to not be in a transaction."""
    conn = pgdb.connect(host='localhost', database='postgres', user='mailman', password='mailman')
    old_iso_lvl = conn.isolation_level
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    cursor.execute('DROP DATABASE "%s"' % name) 
    conn.set_isolation_level(old_iso_lvl)

def executeSQL(mlist, commands):
    """Execute a sequence of SQL commands that create tables in the database."""
    database = getConn(mlist)
    store = Store(database)    
    # In case it's called with a string
    if(type(commands) == types.StringType):
        commands = [commands]
    for command in commands:
        if DEBUG_MODE:
            syslog('info', "DlistUtils:(executeSQL)executing query:%s\n", command)
        try:
            store.execute(command)
        except:
            pass

    store.commit()
    store.close()

def create_dlist(mlist):
    """ Set the dynamic sublist options for a mailing list and create the corresponding postgres database and tables."""

    _create_database(mlist.internal_name())
    if DEBUG_MODE:
         syslog('info', "Database created: %s\n", mlist.internal_name())

    executeSQL(mlist, 
            ["CREATE TABLE subscriber (subscriber_id SERIAL PRIMARY KEY,\
                                       mailman_key VARCHAR(255) UNIQUE,\
                                       preference INT2 DEFAULT 1,\
                                       format INT2 DEFAULT 3, \
                                       deleted BOOLEAN DEFAULT FALSE, \
                                       suppress INT2 DEFAULT 0)",
             "CREATE UNIQUE INDEX subscriber_mailman_key ON subscriber(mailman_key)",
             "CREATE TABLE message (message_id SERIAL PRIMARY KEY,\
                                   sender_id INTEGER REFERENCES subscriber,\
                                   subject VARCHAR(255),\
                                   thread_id INTEGER DEFAULT NULL)",
             "CREATE TABLE thread (thread_id SERIAL PRIMARY KEY,\
                                  thread_name CHAR(16),\
                                  base_message_id INTEGER REFERENCES message,\
                                  status INT2 DEFAULT 0,\
                                  parent INTEGER DEFAULT NULL)",
             "CREATE TABLE alias (pseudonym VARCHAR(255) PRIMARY KEY, \
                    subscriber_id INTEGER REFERENCES subscriber)",
             "CREATE TABLE override (subscriber_id INTEGER REFERENCES subscriber,\
                                    thread_id INTEGER NOT NULL REFERENCES thread,\
                                    preference INT2 NOT NULL)"])


    database = getConn(mlist)
    store = Store(database)

    # Needed in case non-subscribers post
    subscriber = Subscriber(mlist)
    subscriber.subscriber_id = 0
    subscriber.suppress = 1
    #"INSERT INTO subscriber (subscriber_id, suppress) VALUES (0,1)")
    store.add(subscriber)

    store.commit()
    store.close()

    alreadyLocked = mlist.Locked()
    if alreadyLocked == 0:
        mlist.Lock(timeout=mm_cfg.LIST_LOCK_TIMEOUT)
    mlist.dlists_enabled = True
    mlist.require_explicit_destination = 0
    mlist.include_list_post_header = 0
    mlist.include_rfc2369_headers = 0
    mlist.loose_email_matching = 1
    mlist.obscure_addresses = 0

    mlist.Save()
    if alreadyLocked == 0:
        mlist.Unlock()

def remove_dlist(listname):
    """ Deletes the corresponding postgres database and tables."""
    _remove_database(listname)
    if DEBUG_MODE:
         syslog('info', "Database %s removed\n", listname)

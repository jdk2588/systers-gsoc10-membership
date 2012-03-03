# A DlistMembership extends the regular member adaptor to back certain
# attributes with a database.
# Additionally, this implements support for loose matching.
#
# original code by Ellen, separated into child class by Andy

import time
from types import StringType
import datetime
import psycopg2

from OldStyleMemberships import OldStyleMemberships as oldm
from Mailman import DlistUtils
from Mailman import mm_cfg
from Mailman.Logging.Syslog import syslog
from Mailman import MemberAdaptor
from Mailman import Errors
from Mailman import Utils
from storm.locals import *
import md5
ISREGULAR = 1
ISDIGEST = 2

class StormMembers(object):
    __storm_table__ = "mailman_test"
    __storm_primary__ = "listname","address"

    listname = Unicode()
    address = Unicode()
    password = Unicode()
    lang = Unicode()
    name = Unicode()
    digest = Unicode()
    delivery_status = Int()
    user_options = Int()

    topics_userinterest = Unicode()    
    bounce_info = Unicode()
    delivery_status_timestamp = DateTime()


class DlistMemberships(oldm):

    def __init__(self, mlist):
        oldm.__init__(self, mlist)
        self.__mlist = mlist
        self.list = self.__mlist.internal_name()


    def _dbconnect(self):
        """Return a connection to the database for a given mailing list.  The argument may be either the mlist object or a string."""
        user = mm_cfg.STORM_MEMBER_DB_USER
        password = mm_cfg.STORM_MEMBER_DB_PASS
        host = mm_cfg.STORM_MEMBER_DB_HOST
        dbname = mm_cfg.STORM_MEMBER_DB_NAME


        db = 'postgres://'+user+':'+password+'@'+host+'/'+dbname
        return create_database(db)


    def __get_cp_member(self, member):
        # First try strict matching
        result, type = self.__get_cp_member_strict(member)
        if result:
            return result, type
        # Now try loose email matching if this list permits it
        try:
            if self.__mlist.loose_email_matching:
                return self.__get_cp_member_loose(member)
        except:
            pass
        return None, None

    # Name changed from __get_cp_member by Ellen
    def __get_cp_member_strict(self, member):
        """Does the member name exactly match the subscribed name?"""
        lcmember = member.lower()
        missing = []
        val = self.__mlist.members.get(lcmember, missing)
        if val is not missing:
            if isinstance(val, StringType):
                return val, ISREGULAR
            else:
                return lcmember, ISREGULAR
        val = self.__mlist.digest_members.get(lcmember, missing)
        if val is not missing:
            if isinstance(val, StringType):
                return val, ISDIGEST
            else:
                return lcmember, ISDIGEST
        return None, None

    def __get_cp_member_loose(self, member):
        """Check if the provided member email address loosely matches any list membership.
        This should only be called if the list permits loose matching.
        We could save time in the future by adding matches to the alias database."""
        lcmember = member.lower()
        try:
            at_split = lcmember.split('@')
            if len(at_split) != 2:
                return None, None
            local = at_split[0]
            domain = at_split[1]

            # Check if member argument is narrower than actual membership;
            # e.g., robin@eng.sun.com vs. robin@sun.com
            domain_split = domain.split('.')[1:]
            while len(domain_split) > 1:
                substring = local + '@' + string.join(domain_split, '.')
                result, type = self.__get_cp_member_strict(substring)
                if result:
                    return result, type
                domain_split = domain_split[1:]

            # e.g., robin@sun.com vs. robin@eng.sun.com
            regstring = local + '@.*\.' + domain
            try:
                regexp = re.compile(regstring)
            except:
                syslog('info', 'OldStyleMemberships.__get_cp_member_loose: error in re.compile')
                syslog('error', 'OldStyleMemberships.__get_cp_member_loose: error in re.compile')
            for mem in self.__mlist.members.keys():
                if regexp.match(mem):
                    val = self.__mlist.members.get(mem)
                    if isinstance(val, StringType):
                        return val, ISREGULAR
                    else:
                        return mem, ISREGULAR
            for mem in self.__mlist.digest_members.keys():
                if regexp.match(mem):
                    val = self.__mlist.members.get(mem)
                    if isinstance(val, StringType):
                        return val, ISREGULAR
                    else:
                        return mem, ISREGULAR
        # Email address in bad format
        except Error, e:
            syslog('info', 'OldStyleMemberships.__get_cp_member_loose: Error in OldStyleMemberships.__get_cp_member_loose')
            syslog('info', e)
            pass

        return None, None
    def getMemberPassword(self, member):
        secret = self.__mlist.passwords.get(member.lower())
        if secret is None:
            raise Errors.NotAMemberError, member
        return secret
    # override to strip whitespace off passwords

    def getOIDMemberPassword(self, member):
         conn = psycopg2.connect("dbname=mailman_members user=mailman password=mailman")
         cur = conn.cursor() 
   #      password = self.__mlist.returnPassword()
         cur.execute("SELECT address,password FROM mailman_test WHERE address = '%s' and openid = 't'" % (member))
         data = cur.fetchall()
         item = len(data)
         if data!=[]: 
          for i in range(0, item):
                if member==data[i][0]:
                   secret = data[i][1]
                  #secret = self.__mlist.passwords.get(member.lower())
                elif secret is None:
                  raise Errors.NotAMemberError, member
         else:
             secret = None 
         return secret

    def authenticateMember(self, member, response):
        secret = self.getMemberPassword(member).strip()
        if secret == response:
            return secret
        return 0
 
    def authenticateOIDMember(self, member, response):
        secret = self.getOIDMemberPassword(member)
        if secret == response:
            return secret
        return 0

    def addNewMember(self, member, **kws):
        if kws.has_key("affect_dlist_database"):
            affect_dlist_database = kws["affect_dlist_database"]
            del kws["affect_dlist_database"]
        else:
            affect_dlist_database = True
        if kws.has_key("digest"):
            digest = kws["digest"]
        else:
            digest = False
        subscriber = DlistUtils.Subscriber(self.__mlist)
        oldm.addNewMember(self, member, **kws)
        if affect_dlist_database:
            if DlistUtils.enabled(self.__mlist):
                subscriber.subscribeToList(member)
                if digest:
                    subscriber.setDigest(member, 1)

#        if oldm.isMember(self,member):
#            raise Errors.MMAlreadyAMember, member
             
        database = self._dbconnect()
        store = Store(database)
        newMember = StormMembers()


        # Parse the keywords
        digest = 0
        password = Utils.MakeRandomPassword()
        language = self.__mlist.preferred_language
        realname = None

        if kws.has_key('digest'):
            digest = kws['digest']
            del kws['digest']
        if kws.has_key('password'):
            password = kws['password']
            del kws['password']
        if kws.has_key('language'):
            language = kws['language']
            del kws['language']
        if kws.has_key('realname'):
            realname = kws['realname']
            del kws['realname']
        # Assert that no other keywords are present
        if kws:
            raise ValueError, kws.keys()

        newMember.delivery_status = MemberAdaptor.ENABLED
        try:
            newMember.listname = unicode(self.list,"utf-8")
        except:
            newMember.listname = self.list
        try:
            newMember.password = unicode(password,"utf-8")
        except:
            newMember.password = password
        try:
            newMember.lang = unicode(language,"utf-8")
        except:
            newMember.lang = language
        try:
            newMember.address   = unicode(member,"utf-8")
        except:
            newMember.address   = member

        if realname:
            try:
                newMember.name = unicode(realname,"utf-8")
            except:
                newMember.name = realname

        # Set the member's default set of options
        if self.__mlist.new_member_options:
            newMember.user_options = self.__mlist.new_member_options

        # If the localpart has uppercase letters in it, then the value in the
        # members (or digest_members) dict is the case preserved address.
        # Otherwise the value is 0.  Note that the case of the domain part is
        # of course ignored.
        #if Utils.LCDomain(member) == member.lower():
        #    value = 0
        #else:
        #    value = member


        if digest:
            newMember.digest = u"Y"
        else:
            newMember.digest = u"N"
        
        store.add(newMember)
        store.commit()
	


    def removeMember(self, member, affect_dlist_database=1):
        subscriber = DlistUtils.Subscriber(self.__mlist)
        oldm.removeMember(self, member)
        memberkey = member.lower()
        if affect_dlist_database and DlistUtils.enabled(self.__mlist):
            subscriber.unsubscribeFromList(memberkey)

        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
        result.remove()
        store.commit()
        


    def changeMemberAddress(self, member, newaddress, nodelete=1):
        subscriber = DlistUtils.Subscriber(self.__mlist)
        oldm.changeMemberAddress(self, member, newaddress, nodelete=0)  #changed nodelete to 0 - Anna
        memberkey = member.lower()
        if DlistUtils.enabled(self.__mlist):
            subscriber.changeAddress(memberkey, newaddress)
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
        result.set(address = unicode(newaddress,"utf-8"))
        store.commit()


    def setMemberPassword(self, member, password):
        oldm.setMemberPassword(self, member, password)
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") ,  StormMembers.listname == unicode(self.list,"utf-8"))
      	result.set(password = unicode(password,"utf-8"))
        store.commit()


    def setDeliveryStatus(self, member, status):
        oldm.setDeliveryStatus(self, member, status)
        subscriber = DlistUtils.Subscriber(self.__mlist)
        memberkey = member.lower()
        enabled = (status == MemberAdaptor.ENABLED)
        if DlistUtils.enabled(self.__mlist):
            subscriber.setDisable(member, (not enabled))
        assert status in (MemberAdaptor.ENABLED,  MemberAdaptor.UNKNOWN,
                          MemberAdaptor.BYUSER,   MemberAdaptor.BYADMIN,
                          MemberAdaptor.BYBOUNCE)

        if status == MemberAdaptor.ENABLED:
            self.setBounceInfo(member,None)
        else:
            database = self._dbconnect()
            store = Store(database)
            time = datetime.datetime.now()
            result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
            result.set(delivery_status = status)
            #result.set(delivery_status_timestamp = unicode(time.ctime(),"utf-8"))
            result.set(delivery_status_timestamp = time)
            store.commit()

    def setMemberOption(self, member, flag, value):
        subscriber = DlistUtils.Subscriber(self.__mlist)
        oldm.setMemberOption(self, member, flag, value)
        if flag == mm_cfg.Digests and DlistUtils.enabled(self.__mlist):
            subscriber.setDigest(self.__mlist, member, value)
        missing = []
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
        
        if flag == mm_cfg.Digests:
            if value:
                # Be sure the list supports digest delivery
                if not self.__mlist.digestable:
                    raise Errors.CantDigestError
                # The user is turning on digest mode
                for members in result:
                    if(members.digest == unicode("Y","utf-8")):
                        raise Errors.AlreadyReceivingDigests, member
                cpuser = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"), StormMembers.digest == unicode("N","utf-8"))
                if cpuser is None:
                    raise Errors.NotAMemberError, member
                result.set(digest = u"Y")
                store.commit()
            else:
                # Be sure the list supports regular delivery
                if not self.__mlist.nondigestable:
                    raise Errors.MustDigestError
                # The user is turning off digest mode
                for members in result:
                    if(members.digest == unicode("N","utf-8")):
                        raise Errors.AlreadyReceivingRegularDeliveries, member
                cpuser = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"), StormMembers.digest == unicode("Y","utf-8"))
                if cpuser is None:
                    raise Errors.NotAMemberError, member
                result.set(digest = u"N")
                store.commit()
                # When toggling off digest delivery, we want to be sure to set
                # things up so that the user receives one last digest,
                # otherwise they may lose some email
                #self.__mlist.one_last_digest[memberkey] = cpuser
            # We don't need to touch user_options because the digest state
            # isn't kept as a bitfield flag.
            return
        options = 0
        if value:
            options = options|flag
        else:
            options = options & ~flag

        result.set(user_options = options)
        store.commit()



    def setMemberLanguage(self, member, language):
        oldm.setMemberLanguage(self, member, language)
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
        try:
            result.set(lang = unicode(language,"utf-8"))
        except:
            result.set(lang = language)
        store.commit()


    def setMemberName(self, member, realname):
        oldm.setMemberName(self, member, realname)
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8"), StormMembers.listname == unicode(self.list,"utf-8"))
        try:
            result.set(name = unicode(realname,"utf-8"))
        except:
            result.set(name = realname)
        store.commit()


    def setMemberTopics(self, member, topics):
        oldm.setMemberTopics(self, member, topics)
        if topics is None:
            oldm.setMemberTopics(self, member, topics)
            return
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8"), StormMembers.listname == unicode(self.list,"utf-8"))
        result.set(topics_userinterest = unicode(topics,"utf-8"))
        store.commit()


    def setBounceInfo(self, member, info):
        oldm.setBounceInfo(self, member, info)
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8"), StormMembers.listname == unicode(self.list,"utf-8"))
        if info is None:
            result.set(bounce_info = unicode("","utf-8"))
            result.set(delivery_status_timestamp = 0)
        else:
            result.set(bounce_info = unicode(info,"utf-8"))
        store.commit()

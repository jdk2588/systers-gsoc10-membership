import time
from types import StringType
import datetime

from OldStyleMemberships import OldStyleMemberships as oldm
from Mailman import mm_cfg
from Mailman import Utils
from Mailman import Errors
from Mailman import MemberAdaptor
from Mailman.Logging.Syslog import syslog
from storm.locals import *

ISREGULAR = 1
ISDIGEST = 2

class StormMembers(object):
    """Membership attributes to be stored in the database"""
    __storm_table__ = "mailman_test"
    __storm_primary__ =  "listname","address"
    
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


class StormMemberships(oldm):
    def __init__(self, mlist):
        oldm.__init__(self,mlist)
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


    def addNewMember(self, member, **kws):
        """Add new member to the database"""

        if oldm.isMember(self,member):
            raise Errors.MMAlreadyAMember, member
             
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
	oldm.addNewMember(self,member,**kws)


       
    def removeMember(self, member):
        """Remove member from db"""
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
        result.remove()
        store.commit()
        oldm.removeMember(self,member)

    def changeMemberAddress(self, member, newaddress, nodelete=0):
        """Change member address"""
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
        result.set(address = unicode(newaddress,"utf-8"))
        store.commit()
        oldm.changeMemberAddress(self, member, newaddress, nodelete)

    def setMemberPassword(self, memberkey, password):
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(memberkey,"utf-8"),  StormMembers.listname == unicode(self.list,"utf-8"))
        result.set(password = unicode(password,"utf-8"))
        store.commit()
        oldm.setMemberPassword(self, memberkey, password)

    def setMemberLanguage(self, memberkey, language):
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(memberkey,"utf-8") , StormMembers.listname == unicode(self.list,"utf-8"))
        try:
            result.set(lang = unicode(language,"utf-8"))
        except:
            result.set(lang = language)
        store.commit()
        oldm.setMemberLanguage(self, memberkey, language)

    def setMemberOption(self, member, flag, value):
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
        oldm.setMemberOption(self, member, flag, value)

    def setMemberName(self, member, realname):
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8"), StormMembers.listname == unicode(self.list,"utf-8"))
        try:
            result.set(name = unicode(realname,"utf-8"))
        except:
            result.set(name = realname)
        store.commit()
        oldm.setMemberName(self, member, realname)

    def setMemberTopics(self, member, topics):
        if topics is None:
            oldm.setMemberTopics(self, member, topics)
            return
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8"), StormMembers.listname == unicode(self.list,"utf-8"))
        result.set(topics_userinterest = unicode(topics,"utf-8"))
        store.commit()
        oldm.setMemberTopics(self, member, topics)

    def setDeliveryStatus(self, member, status):
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
        oldm.setDeliveryStatus(self, member, status)


    def setBounceInfo(self, member, info):
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.address == unicode(member,"utf-8"), StormMembers.listname == unicode(self.list,"utf-8"))
        if info is None:
            result.set(bounce_info = unicode("","utf-8"))
            result.set(delivery_status_timestamp = 0)
        else:
            result.set(bounce_info = unicode(info,"utf-8"))
        store.commit()
        oldm.setBounceInfo(self, member, info)

##Read methods##

    def __get_cp_member(self, member):
        missing = []
        database = self._dbconnect()
        store = Store(database)
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))
        if result is not missing:
            for members in result:
                if members.digest == u"N":
                    return member, ISREGULAR
                else:
                    return member, ISDIGEST
        return None,None


    def getRegularMemberKeys(self):
        """Returns Regular members in list: listName"""
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.digest == u"N",  StormMembers.listname == unicode(self.list,"utf-8"))
        regularMembers = [member.address for member in result]
        return regularMembers


    def getDigestMemberKeys(self):
        """Returns the digest members in list: listName"""
        database = self._dbconnect()
        store = Store(database)
        result = store.find(StormMembers, StormMembers.digest == u"Y" ,StormMembers.listname == unicode(self.list,"utf-8"))
        digestMembers = [member.address for member in result]
        return digestMembers



    def getMembers(self):
        return self.getRegularMemberKeys() + self.getDigestMemberKeys()



    def getMemberKey(self, member):
        cpaddr, where = self.__get_cp_member(member)
        if cpaddr is None:
            raise Errors.NotAMemberError, member
        return member


    def getMemberCPAddress(self, member):
        cpaddr, where = self.__get_cp_member(member)
        if cpaddr is None:
            raise Errors.NotAMemberError, member
        return cpaddr

    def getMemberCPAddresses(self, members):
        return [self.__get_cp_member(member)[0] for member in members]

    def authenticateMember(self, member, response):
        passwd = self.getMemberPassword(member)
        secret = unicode(passwd,"utf-8")
        if secret == unicode(response,"utf-8"):
            return secret
        return 0

    def getMemberPassword(self, member):
        """Returns the password for list:listName for user:member"""
        database = self._dbconnect()
        store = Store(database)
        missing = []
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))

        if result is not missing:
            for members in result:
                password = members.password
            return password.encode('ascii')
        raise Errors.NotAMemberError, member


    def getMemberName(self, member):
        if not oldm.isMember(self,member):
            raise Errors.MMAlreadyAMember, member

        database = self._dbconnect()
        store = Store(database)
        missing = []
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))
        
        if result is not missing:
            for members in result:
                name = members.name 
            return name
        return None


    def getMemberLanguage(self, member):
        if not oldm.isMember(self,member):
            raise Errors.MMAlreadyAMember, member

        database = self._dbconnect()
        store = Store(database)
        missing = []
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))

        if result is not missing:
            for members in result:
                language = members.lang 
            if language in self.__mlist.GetAvailableLanguages():
                return language
        return self.__mlist.preferred_language



    def getMemberOption(self, member,flag):
        if flag == mm_cfg.Digests:
            cpaddr, where = self.__get_cp_member(member)
            return where == ISDIGEST
        database = self._dbconnect()
        store = Store(database)
        missing = []
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))

        if result is not missing:
            for members in result:
                option = members.user_options
            return not not (option & flag)

    def getMemberTopics(self, member):
        if not oldm.isMember(self,member):
            raise Errors.MMAlreadyAMember, member

        database = self._dbconnect()
        store = Store(database)
        missing = []
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))

        if result is not missing:
            for members in result:
                topics = members.topics_userinterest
            return topics

    def getDeliveryStatus(self, member):
        if not oldm.isMember(self,member):
            raise Errors.MMAlreadyAMember, member

        database = self._dbconnect()
        store = Store(database)
        missing = []
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))

        if result is not missing:
            for members in result:
                status  = members.delivery_status
            return status
        return None

    def getDeliveryStatusMembers(self, status=(MemberAdaptor.UNKNOWN,
                                               MemberAdaptor.BYUSER,
                                               MemberAdaptor.BYADMIN,
                                               MemberAdaptor.BYBOUNCE)):
        return [member for member in oldm.getMembers(self)
                if self.getDeliveryStatus(member) in status]

    def getDeliveryStatusChangeTime(self, member):
        if not oldm.isMember(self,member):
            raise Errors.MMAlreadyAMember, member

        database = self._dbconnect()
        store = Store(database)
        missing = []
        delivery_status_changetime = 0
        try:
            result = store.find(StormMembers,StormMembers.address == unicode(member,"utf-8"),StormMembers.listname == unicode(self.list,"utf-8"))
        except:
            result = store.find(StormMembers,StormMembers.address == member , StormMembers.listname == unicode(self.list,"utf-8"))

        if result is not missing:
            for members in result:
                delivery_status_changetime = members.delivery_status_timestamp
	    return delivery_status_changetime


    def getBouncingMembers(self):
        database = self._dbconnect()
        store = Store(database)
        bounce_info_list = []
        result = store.find(StormMembers, StormMembers.listname == unicode(self.list,"utf-8"))
        for members in result:
            if members.bounce_info is None:
                pass
            else:
                bounce_info_list.append(members.address)
         
        return bounce_info_list


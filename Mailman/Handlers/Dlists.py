
"""Handles dynamic sublists 
"""

from Mailman.Handlers import Decorate
from Mailman.Logging.Utils import LogStdErr
from Mailman.Logging.Syslog import syslog
from Mailman import Errors
from Mailman import ErrorsDlist
from Mailman import DlistUtils
from Mailman.mm_cfg import DEBUG_MODE

LogStdErr('error', 'dlists')

def get_malformed_msg_txt(mlist):
    vars = dict(host=mlist.host_name, listname=mlist.internal_name())
    return "Your message was rejected because it was sent to an invalid address.  If you want to add a message to an existing conversation,send it to %(listname)s+conversation@%(host)s, replacing 'conversation' with the name of the existing conversation.  If you want to start a new conversation on %(listname)s, send your message to %(listname)s+new@%(host)s\n\n" % vars

def process(mlist, msg, msgdata):
    """ Process a command for a dlist given in an email, such as create a new thread, subscribe to or unsubscribe from a thread"""
    if not DlistUtils.enabled(mlist):
        return
    thread = DlistUtils.Thread(mlist)
    # Ensure that there is a subject, even if it's the empty string
    if not msg.has_key('Subject'):
        msg['Subject'] = ''

    try:
        # To and CC could be anything, but we know x-original-to will be
        # the list address in question.
        incomingAddress = msg['X-Original-To'].split('@')[0] # strip domain
        commands = incomingAddress.split('+')[1:] # strip listname
    except Exception, e:
        raise ErrorsDlist.MalformedRequest(get_malformed_msg_txt(mlist)) 
    
    if not len(commands):
        raise ErrorsDlist.MalformedRequest(get_malformed_msg_txt(mlist)) 

    # Check whether it is a new, continue, subscribe, unsubscribe, or malformed
    if commands[0] == 'new':
        if len(commands) > 1:
            thread.newThread(msg, msgdata, commands[1])
        else:
            thread.newThread(msg, msgdata)
    else:
        thread_reference = commands[0]
        (thread_id, thread_name) = thread.threadIDandName(thread_reference)
        msgdata['thread_id'] = thread_id
        msgdata['thread_name'] = thread_name

        if len(commands) == 1:
            msgdata['command'] = 'continue'
            thread.continueThread(msg, msgdata, thread_reference)

        elif len(commands) == 2:
            subcommand = commands[1]
            if DEBUG_MODE:
                syslog('info', 'Command to %s for thread %s', subcommand, thread_reference)
            if subcommand == 'subscribe':
                thread.subscribeToThread(msg, msgdata)
            elif subcommand == 'unsubscribe':
                thread.unsubscribeFromThread(msg, msgdata)
            else:
                raise ErrorsDlist.MalformedRequest
            # Not an error, but we're done with it
            raise Errors.DiscardMessage
        else:
            raise ErrorsDlist.MalformedRequest


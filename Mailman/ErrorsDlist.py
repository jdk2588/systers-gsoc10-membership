"""Mailman errors related to dynamic sublists."""

import Mailman.i18n
from Mailman import Errors

class MalformedRequest(Errors.RejectMessage):
    """A malformed request involving a dynamic sublist."""
    pass

class NonexistentThreadRequest(Errors.RejectMessage):
    """A reference to a nonexistent thread."""
    def __init__(self, message):
        Errors.RejectMessage.__init__(self, message)
    pass

class DatabaseIntegityError(Errors.MMListError):
    """A database integrity error in the dlist code"""
    pass

class InternalError(Errors.RejectMessage):
    """Internal error -- alert user and administrator"""
    def __init__(self):
        Errors.RejectMessage.__init__(self, "Your message could not be processed because of an internal error (software problem).  We are very sorry.  The system administrator has been notified of the problem.")
    pass

class NotMemberError(Errors.RejectMessage):
    """Request made by a non-member"""
    pass

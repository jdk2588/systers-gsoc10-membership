# Copyright (C) 2001-2004 by the Free Software Foundation, Inc.
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

"""Dlist's specialization of the user description class"""

from types import UnicodeType
from Mailman.UserDesc import UserDesc

class DlistUserDesc(UserDesc):
    def __init__(self, address=None, fullname=None, password=None,
                 digest=None, lang=None, essay=None):
        UserDesc.__init__(self, address, fullname, password, digest, lang)
        if essay is not None:
            self.essay = essay

    def __iadd__(self, other):
        UserDesc.__iadd__(self, other)
        if getattr(other, 'essay', None) is not None:
            self.essay = other.essay
        return self

## I didn't inherit, I duplicated the work here, as I couldn't figure out how to concatenate the two strings correctly
    def __repr__(self):
        address = getattr(self, 'address', 'n/a')
        fullname = getattr(self, 'fullname', 'n/a')
        password = getattr(self, 'password', 'n/a')
        digest = getattr(self, 'digest', 'n/a')
        if digest == 0:
            digest = 'no'
        elif digest == 1:
            digest = 'yes'
        language = getattr(self, 'language', 'n/a')
        essay = getattr(self, 'essay', 'n/a')
        # Make sure fullname, password and essay are encoded if they're strings
        if isinstance(fullname, UnicodeType):
            fullname = fullname.encode('ascii', 'replace')
        if isinstance(password, UnicodeType):
            password = password.encode('ascii', 'replace')
        if isinstance(essay, UnicodeType):
            essay = essay.encode('ascii', 'replace')
        return '<UserDesc %s (%s) [%s] [digest? %s] [%s] [%s] >' % (
            address, fullname, password, digest, language, essay)


        

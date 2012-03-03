# Copyright (C) 1998,1999,2000,2001 by the Free Software Foundation, Inc.
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
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Dynamic sublist processor."""


from Mailman import mm_cfg
from Mailman.Queue.Runner import Runner
from Mailman.Queue.IncomingRunner import IncomingRunner
from Mailman.Logging.Syslog import syslog


class DlistRunner(IncomingRunner):
    QDIR = mm_cfg.DLISTQUEUE_DIR

    # Messages here are actually modified duplicates of the original msg
    # (which continued on with recips=None), so msgs in this queue only
    # need to be cleaned up and sent.
    def _get_pipeline(self, mlist, msg, msgdata):
        return ['CookHeaders', 'ToOutgoing']


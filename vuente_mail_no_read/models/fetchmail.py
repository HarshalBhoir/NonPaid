# -*- coding: utf-8 -*-
import logging
import poplib
import time
from imaplib import IMAP4
from imaplib import IMAP4_SSL
from poplib import POP3
from poplib import POP3_SSL
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO

from openerp.osv import fields, osv
from openerp import tools, api, SUPERUSER_ID
from openerp.tools.translate import _
from openerp.exceptions import UserError

_logger = logging.getLogger(__name__)
MAX_POP_MESSAGES = 50
MAIL_TIMEOUT = 60

# Workaround for Python 2.7.8 bug https://bugs.python.org/issue23906
poplib._MAXLINE = 65536

class tci_company(osv.osv):

    _inherit = "fetchmail.server"
    
    def fetch_mail(self, cr, uid, ids, context=None):
        """WARNING: meant for cron usage only - will commit() after each email!"""
        context = dict(context or {})
        context['fetchmail_cron_running'] = True
        mail_thread = self.pool.get('mail.thread')
        action_pool = self.pool.get('ir.actions.server')
        for server in self.browse(cr, uid, ids, context=context):
            _logger.info('start checking for new emails on %s server %s', server.type, server.name)
            context.update({'fetchmail_server_id': server.id, 'server_type': server.type})
            count, failed = 0, 0
            imap_server = False
            pop_server = False
            if server.type == 'imap':
                try:
                    imap_server = server.connect()
                    imap_server.select()
                    result, data = imap_server.search(None, '(UNSEEN)')
                    for num in data[0].split():
                        res_id = None
                        result, data = imap_server.fetch(num, '(RFC822)')
                        imap_server.store(num, '-FLAGS', '\\Seen')
                        try:
                            res_id = mail_thread.message_process(cr, uid, server.object_id.model,
                                                                 data[0][1],
                                                                 save_original=server.original,
                                                                 strip_attachments=(not server.attach),
                                                                 context=context)
                        except Exception:
                            _logger.info('Failed to process mail from %s server %s.', server.type, server.name, exc_info=True)
                            failed += 1
                        if res_id and server.action_id:
                            action_pool.run(cr, uid, [server.action_id.id], {'active_id': res_id, 'active_ids': [res_id], 'active_model': context.get("thread_model", server.object_id.model)})
                        #imap_server.store(num, '+FLAGS', '\\Seen')
                        cr.commit()
                        count += 1
                    _logger.info("Fetched %d email(s) on %s server %s; %d succeeded, %d failed.", count, server.type, server.name, (count - failed), failed)
                except Exception:
                    _logger.info("General failure when trying to fetch mail from %s server %s.", server.type, server.name, exc_info=True)
                finally:
                    if imap_server:
                        imap_server.close()
                        imap_server.logout()
            elif server.type == 'pop':
                try:
                    while True:
                        pop_server = server.connect()
                        (numMsgs, totalSize) = pop_server.stat()
                        pop_server.list()
                        for num in range(1, min(MAX_POP_MESSAGES, numMsgs) + 1):
                            (header, msges, octets) = pop_server.retr(num)
                            msg = '\n'.join(msges)
                            res_id = None
                            try:
                                res_id = mail_thread.message_process(cr, uid, server.object_id.model,
                                                                     msg,
                                                                     save_original=server.original,
                                                                     strip_attachments=(not server.attach),
                                                                     context=context)
                                pop_server.dele(num)
                            except Exception:
                                _logger.info('Failed to process mail from %s server %s.', server.type, server.name, exc_info=True)
                                failed += 1
                            if res_id and server.action_id:
                                action_pool.run(cr, uid, [server.action_id.id], {'active_id': res_id, 'active_ids': [res_id], 'active_model': context.get("thread_model", server.object_id.model)})
                            cr.commit()
                        if numMsgs < MAX_POP_MESSAGES:
                            break
                        pop_server.quit()
                        _logger.info("Fetched %d email(s) on %s server %s; %d succeeded, %d failed.", numMsgs, server.type, server.name, (numMsgs - failed), failed)
                except Exception:
                    _logger.info("General failure when trying to fetch mail from %s server %s.", server.type, server.name, exc_info=True)
                finally:
                    if pop_server:
                        pop_server.quit()
            server.write({'date': time.strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT)})
        return True

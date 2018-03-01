from odoo import _, api, fields, models, registry, SUPERUSER_ID
import threading

class XMailconfigEmailFooter(models.Model):
	_inherit = 'res.partner'

	@api.multi
	def _notify(self, message, force_send=False, send_after_commit=True, user_signature=True):
		""" Method to send email linked to notified messages. The recipients are
		the recordset on which this method is called.

		:param boolean force_send: send notification emails now instead of letting the scheduler handle the email queue
		:param boolean send_after_commit: send notification emails after the transaction end instead of durign the
										  transaction; this option is used only if force_send is True
		:param user_signature: add current user signature to notification emails """
		if not self.ids:
			return True

		# existing custom notification email
		base_template = None
		if message.model and self._context.get('custom_layout', False):
			base_template = self.env.ref(self._context['custom_layout'], raise_if_not_found=False)
		if not base_template:
			base_template = self.env.ref('remove_footer_copyright.mail_template_notification_default_no_sentby')

		base_template_ctx = self._notify_prepare_template_context(message)
		#Change here
		if not base_template_ctx['signature']:
			base_template_ctx['signature'] = False
		base_mail_values = self._notify_prepare_email_values(message)

		# classify recipients: actions / no action
		if message.model and message.res_id and hasattr(self.env[message.model], '_message_notification_recipients'):
			recipients = self.env[message.model].browse(message.res_id)._message_notification_recipients(message, self)
		else:
			recipients = self.env['mail.thread']._message_notification_recipients(message, self)

		emails = self.env['mail.mail']
		recipients_nbr, recipients_max = 0, 50
		for email_type, recipient_template_values in recipients.items():
			if recipient_template_values['followers']:
				# generate notification email content
				template_fol_values = dict(base_template_ctx, **recipient_template_values)  # fixme: set button_unfollow to none
				template_fol_values['has_button_follow'] = False
				template_fol = base_template.with_context(**template_fol_values)
				# generate templates for followers and not followers
				fol_values = template_fol.generate_email(message.id, fields=['body_html', 'subject'])
				# send email
				new_emails, new_recipients_nbr = self._notify_send(fol_values['body'], fol_values['subject'], recipient_template_values['followers'], **base_mail_values)
				# update notifications
				self._notify_udpate_notifications(new_emails)

				emails |= new_emails
				recipients_nbr += new_recipients_nbr
			if recipient_template_values['not_followers']:
				# generate notification email content
				template_not_values = dict(base_template_ctx, **recipient_template_values)  # fixme: set button_follow to none
				template_not_values['has_button_unfollow'] = False
				template_not = base_template.with_context(**template_not_values)
				# generate templates for followers and not followers
				not_values = template_not.generate_email(message.id, fields=['body_html', 'subject'])
				# send email
				new_emails, new_recipients_nbr = self._notify_send(not_values['body'], not_values['subject'], recipient_template_values['not_followers'], **base_mail_values)
				# update notifications
				self._notify_udpate_notifications(new_emails)

				emails |= new_emails
				recipients_nbr += new_recipients_nbr

		# NOTE:
		#   1. for more than 50 followers, use the queue system
		#   2. do not send emails immediately if the registry is not loaded,
		#      to prevent sending email during a simple update of the database
		#      using the command-line.
		test_mode = getattr(threading.currentThread(), 'testing', False)
		if force_send and recipients_nbr < recipients_max and \
				(not self.pool._init or test_mode):
			email_ids = emails.ids
			dbname = self.env.cr.dbname
			_context = self._context

			def send_notifications():
				db_registry = registry(dbname)
				with api.Environment.manage(), db_registry.cursor() as cr:
					env = api.Environment(cr, SUPERUSER_ID, _context)
					env['mail.mail'].browse(email_ids).send()

			# unless asked specifically, send emails after the transaction to
			# avoid side effects due to emails being sent while the transaction fails
			if not test_mode and send_after_commit:
				self._cr.after('commit', send_notifications)
			else:
				emails.send()

		return True

# TCK-101 — Password reset not working
Customer: Meridian Logistics (support rep: J. Alvarez)
Opened: 2026-09-10

Customer reports the "forgot password" email never arrives. Confirmed their
account email is correct in the CRM. Checked spam folder with them, still
nothing. Likely our transactional email provider throttling their domain.

Resolution: Manually triggered a password reset link via the admin console
and sent it directly to the customer. Recommended they whitelist
no-reply@ourapp.com.
Status: Closed

"""Generated draft based on the application's actual server features. Never auto-published."""

from app.modules.legal_pages.schemas import PolicyContent, Section
from app.shared.date_time.business_calendar import business_today


def initial_policy():
    return PolicyContent(
        publisher_name="Madhav Bharat Gas Agency",
        customer_app_name="Madhav Bharat Gas Agency Customer App",
        merchant_app_name="Madhav Bharat Gas Agency Merchant App",
        rider_app_name="Madhav Bharat Gas Agency Rider App",
        effective_date=business_today(),
        sections=[
            Section(heading=heading, body=body)
            for heading, body in [
                (
                    "About this policy",
                    "This Privacy Policy explains how we handle information through our Customer, Merchant and Rider apps and the related administration and delivery services. The publisher identified above is responsible for operating these services. Each app has a different role; the sections below explain the information relevant to that role.",
                ),
                (
                    "Customer app",
                    "We process account and contact details such as name, mobile number, business or owner name, email when provided, delivery address and delivery-site details. Registration and eligibility checks can include identity, business and tax documents such as Aadhaar, PAN, GST, FSSAI or MSME details and uploaded images, depending on the customer type. We process orders, cylinder deliveries and returns, invoices, payment amounts, UPI transaction references or uploaded payment receipts, credit eligibility and outstanding balances to provide and support the service.",
                ),
                (
                    "Merchant app",
                    "We process merchant and staff account details, business and contact information, role and permission assignments, customer and delivery-site records, customer verification records, orders, cylinder stock and movements, invoices, payment and reconciliation records, expenses, fuel records, receipt images, vehicle and delivery-team assignments, reports and task activity. Access to these records depends on the merchant relationship, assigned duties and permissions.",
                ),
                (
                    "Rider app",
                    "We process rider or delivery-team identity and contact details, assigned vehicles and deliveries, work status, delivery progress and verification events. For assigned deliveries, riders receive the customer contact and address details needed to fulfil the delivery. We process cylinder handover and empty-return counts, delivery confirmation results, payment collection details and payment-proof images supplied during delivery. Location processing is explained separately below.",
                ),
                (
                    "Why we use information",
                    "We use information to register and authenticate accounts, verify eligibility and business records, fulfil and track LPG orders and deliveries, maintain cylinder balances and stock, issue invoices, manage payments and reconciliation, operate approved credit arrangements, coordinate delivery staff and vehicles, send service notifications, provide support, keep operational audit records and help prevent misuse or fraud. Some records are also used to meet applicable tax, accounting, safety and legal obligations.",
                ),
                (
                    "Permissions and files",
                    "Location permissions support location-enabled delivery and address-verification features as described below. Camera or system file/photo selection may be used when you choose to submit verification documents, receipts or payment proof. Selected or captured files are sent to the service when submitted. Notification permission, where applicable, enables operational messages. You can manage permissions in device settings; refusing a permission can limit the corresponding feature. Do not upload documents or information unrelated to the requested purpose.",
                ),
                (
                    "Account, device and security information",
                    "Authentication and service records can include mobile-number verification events, login and session activity, an app-provided installation identifier, device name, operating-system or app information when supplied, push-notification tokens, request information and security or audit logs. We use these records to keep accounts signed in, deliver notifications, investigate failures and protect the service.",
                ),
                (
                    "Who receives information",
                    "Information is available to authorised agency administrators, the relevant merchant and assigned staff or delivery personnel to the extent needed for their duties. Service providers supporting hosting, storage, authentication, messaging, notifications and related operations may process data for those purposes. UPI payments involve the banking or UPI app you choose and its own privacy terms. Invoice or compliance information may be shared with authorised tax or e-invoicing services when that feature is used. We may disclose information where required by law or necessary to investigate fraud, protect users or exercise legal rights. Provider and SDK details are given below.",
                ),
                (
                    "Security",
                    "We use HTTPS for the public service and authenticated, role- and ownership-based access controls for protected business records. Access is restricted according to operational responsibilities. No online service or transmission can be guaranteed completely secure. Keep your device and sign-in credentials secure, and never give another person your login OTP. Provide a delivery confirmation code only for the delivery you intend to confirm.",
                ),
                (
                    "Retention",
                    "We retain account and operational information for the time needed to provide the service, resolve disputes, investigate misuse and meet applicable legal or business-record obligations. Invoices, tax records, financial transactions and delivery records may need to be retained after account closure. Retention depends on the record and applicable requirements; we do not apply one fixed deletion period to every category. Backup copies may persist until the corresponding backup retention cycle ends.",
                ),
                (
                    "Privacy requests and account deletion",
                    "Use the privacy contact listed on this page to request access to or correction of your information, raise a privacy concern, or request deletion of your account and associated data. Identify the app and registered mobile number or account so we can locate the record. Do not send a login OTP, password or unnecessary identity documents. We may verify account ownership before acting. Where account deletion is requested, data that is no longer needed should be deleted or anonymised; records that must be retained for legal obligations, transaction reconciliation or dispute handling may be retained for that purpose. Closing access alone is not a substitute for deleting eligible data. Device permissions can also be withdrawn in device settings.",
                ),
                (
                    "Children",
                    "These services are designed for LPG customers, businesses and authorised delivery personnel, rather than for use directed at children. A parent or guardian who believes a child has supplied information should contact us so the information can be reviewed and handled appropriately.",
                ),
                (
                    "Changes to this policy",
                    "We may update this policy when our services or data practices change. The current version and effective date appear on this page. Where a change requires additional notice or consent, that notice or consent must be provided through the relevant app or other appropriate channel.",
                ),
            ]
        ],
    )

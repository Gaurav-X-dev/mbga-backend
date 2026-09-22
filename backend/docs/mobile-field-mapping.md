# Mobile Field Mapping

## Request Fields

| Frontend camelCase | Backend accepted | Stored in |
| --- | --- | --- |
| `customerType` | `customerType`, `customer_type` | `customer_profiles.customer_type` |
| `businessName` | `businessName`, `name` | `customer_profiles.name` |
| `ownerName` | `ownerName` | `customer_profiles.owner_name` |
| `mobile` | merchant create only; onboarding mobile is session-derived | `customer_profiles.mobile_number` |
| `email` | `email` | `customer_profiles.email` |
| `deliveryAddress.line1` | `deliveryAddress.line1` | `address_line1` |
| `deliveryAddress.line2` | `deliveryAddress.line2` | `address_line2` |
| `deliveryAddress.city` | `deliveryAddress.city` | `address_city` |
| `deliveryAddress.state` | `deliveryAddress.state` | `address_state` |
| `deliveryAddress.pincode` | `deliveryAddress.pincode` | `address_pincode` |
| `documents[].type` | `documents[].type` | `customer_documents.document_type` |
| `documents[].number` | `documents[].number` | encrypted number + keyed lookup hash |
| `documents[].fileName` | `documents[].fileName` | uploaded `fileId` |
| `sites[].isPrimary` | `sites[].isPrimary` | `customer_delivery_sites.is_primary` |

## Status Values

Customer account statuses returned to mobile: `NEW`, `PENDING`, `APPROVED`, `REJECTED`, `SUSPENDED`.

KYC statuses: `NOT_SUBMITTED`, `PENDING`, `VERIFIED`, `REJECTED`.

Document statuses: `UPLOADED`, `VERIFIED`, `REJECTED`.

`next_action` values: `COMPLETE_PROFILE`, `SUBMIT_DOCUMENTS`, `WAIT_FOR_APPROVAL`, `SIGN_IN`, `OPEN_CUSTOMER_HOME`, `CONTACT_SUPPORT`.

## Errors

Build `fieldErrors` from:

```ts
for (const item of detail.fields ?? []) fieldErrors[item.field] = item.message;
```

Mobile business logic must use `detail.code`. `detail.message` is display text and must not be parsed for navigation.

## Seeded Permissions

| Spec action | Seeded permission |
| --- | --- |
| Add Customer | `customers.create` |
| View Customer | `customers.view` |
| Approve Customer | `customers.approve` |
| Reject Customer | `customers.reject` |
| Review KYC queue/detail | `customers.review` |
| Review/open documents | `customer_documents.review` |
| Eligibility for order creation | `orders.create` |


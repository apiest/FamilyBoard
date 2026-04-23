# Security policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in FamilyBoard, please
**do not open a public issue**. Instead, report it privately via GitHub's
[private vulnerability reporting](https://github.com/apiest/FamilyBoard/security/advisories/new)
form.

You can expect:

- An acknowledgement within a reasonable time (this is a personal,
  best-effort project — there is no SLA).
- A coordinated disclosure timeline once the issue is triaged.

## Supported versions

Only the latest released version of FamilyBoard receives fixes. Older
versions are not patched.

## Scope

In scope:

- The Home Assistant custom integration code under
  `custom_components/familyboard/`.
- The Lovelace cards under `custom_components/familyboard/frontend/`.

Out of scope:

- Vulnerabilities in Home Assistant itself — please report those to the
  [Home Assistant project](https://www.home-assistant.io/security/).
- Vulnerabilities in third-party Lovelace cards (Bubble Card, mushroom,
  card-mod, …) used alongside FamilyBoard — report those to their
  respective maintainers.
- Misconfiguration of a user's own Home Assistant instance.

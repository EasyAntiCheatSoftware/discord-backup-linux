# Security reports

The current release series is 1.4.x. Older snapshots have no separate maintenance branch.

Report vulnerabilities through this repository's GitHub **Security → Report a vulnerability** option when available. If private reporting is unavailable, open an issue asking for a private reporting channel without exploit details or sensitive data. Do not attach real tokens, passphrases, backups, private credential files, account exports, or unredacted HTTP traffic to a public issue.

Include the affected version, entry point, prerequisites, a minimal synthetic reproduction, and the observed impact. An imported backup should be synthetic. Distinguish control of a backup field or remote Discord metadata from preexisting control of the local user's code, configuration, or files.

The application is a single-user Linux CLI, not a sandbox or a multi-user service. It trusts the invoking OS/account, Python/GnuPG dependencies, and configured HTTPS proxy/CA environment. Optional unattended token/passphrase files are plaintext protected by permissions. Encryption does not protect an unlocked export, a compromised user account, or a forgotten passphrase. Private Discord endpoints and account-automation restrictions are external compatibility risks.

Release checks combine an explicit file manifest, credential/private-path pattern checks, package content comparison and manual payload inspection. Pattern checks are a backstop; they cannot prove arbitrary source text contains no secret. See docs/REVIEW.md for tested controls and limits.

# Vault storage

VAULT-001. Store credentials in KDBX. Keep passwords, key material, OTP seeds, and protected fields out of request logs and regular entry listings.

VAULT-002. All mutations go through one service path. Verify encrypted candidates before replacing an existing database. Preserve unknown KDBX data on ordinary edits.

VAULT-003. REST and MCP enforce the same vault permissions. Use synthetic vaults for all automated checks.

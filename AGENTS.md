# Agent Instructions

## POC Boundary

POCs under `pocs/` are knowledge and design extraction sources only. Product
runtime code must not import, execute, shell out to, or otherwise depend on
files under `pocs/`.

When product behavior is promoted from a POC, move the required logic into a
product-owned module, script, or service under `editor/` and cover it with
product tests. References to POC files are acceptable only in documentation,
research notes, or one-off migration tools that are not part of the product
runtime path.

Knowledge and design extraction does not mean copying POC files verbatim. If a
POC idea is promoted into the product, re-design it behind product-owned
contracts, adapters, data models, and tests.

Any remaining product runtime reference to POC-era scripts, POC-shaped output
files, or POC output roots must be listed in
`docs/architecture/temporary-legacy-dependencies.json` with an owning Ceetrix
story, affected workflow, reason for remaining, and removal condition. New
unlisted runtime references are regressions.

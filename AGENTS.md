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

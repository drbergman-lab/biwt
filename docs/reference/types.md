# `biwt.types`

The public API boundary. Everything that crosses between a host application and BIWT is one
of these three dataclasses.

For prose on how to use them well — including which fields are worth wiring up and which are
reserved — see [the API contract](../integration/api-contract.md).

::: biwt.types
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members:
        - DomainSpec
        - BiwtInput
        - BiwtResult

//! Native secret-custody boundary; renderer-facing code receives no key material.

pub(crate) mod key_custody;

pub(crate) use key_custody::KeyCustody;

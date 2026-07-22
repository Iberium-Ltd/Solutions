//! Final native boundary for opening user-mediated HTTPS destinations.
//!
//! Renderer validation is defense in depth; this module independently accepts
//! only canonical fixed portals, bounded search URLs, and HIBP breach pages.

use reqwest::Url;

const MAX_EXTERNAL_URL_BYTES: usize = 8_192;
const MAX_SEARCH_QUERY_BYTES: usize = 1_024;

const FIXED_PORTALS: &[&str] = &[
    "https://dehashed.com/",
    "https://www.spokeo.com/",
    "https://www.intelius.com/",
    "https://web.archive.org/",
    "https://lookup.icann.org/",
    "https://find-and-update.company-information.service.gov.uk/",
    "https://github.com/search?type=users",
    "https://myactivity.google.com/results-about-you",
    "https://haveibeenpwned.com/",
    "https://haveibeenpwned.com/API/v3",
];

pub(crate) fn open_external_url(value: &str) -> Result<(), ExternalUrlError> {
    // Pass only the canonical URL returned by the closed allowlist validator.
    let url = validate_external_url(value)?;
    if crate::platform::open_external_url(url.as_str()) {
        Ok(())
    } else {
        Err(ExternalUrlError::OpenFailed)
    }
}

fn validate_external_url(value: &str) -> Result<Url, ExternalUrlError> {
    if value.is_empty() || value.len() > MAX_EXTERNAL_URL_BYTES {
        return Err(ExternalUrlError::Refused);
    }
    let url = Url::parse(value).map_err(|_| ExternalUrlError::Refused)?;
    if url.scheme() != "https"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port().is_some()
        || url.fragment().is_some()
        || url.as_str() != value
    {
        return Err(ExternalUrlError::Refused);
    }

    if FIXED_PORTALS.contains(&value) || valid_hibp_breach_url(&url) || valid_search_url(&url) {
        Ok(url)
    } else {
        Err(ExternalUrlError::Refused)
    }
}

fn valid_hibp_breach_url(url: &Url) -> bool {
    url.host_str() == Some("haveibeenpwned.com")
        && url.query().is_none()
        && url
            .path()
            .strip_prefix("/api/v3/breach/")
            .is_some_and(|name| !name.is_empty() && name.len() <= 256)
}

fn valid_search_url(url: &Url) -> bool {
    let (host, path, query_key, extra_pair) = match (url.host_str(), url.path()) {
        (Some("www.google.com"), "/search") => ("www.google.com", "/search", "q", None),
        (Some("www.bing.com"), "/search") => ("www.bing.com", "/search", "q", None),
        (Some("duckduckgo.com"), "/") => ("duckduckgo.com", "/", "q", None),
        (Some("search.brave.com"), "/search") => {
            ("search.brave.com", "/search", "q", Some(("source", "web")))
        }
        (Some("www.ecosia.org"), "/search") => ("www.ecosia.org", "/search", "q", None),
        (Some("www.startpage.com"), "/sp/search") => {
            ("www.startpage.com", "/sp/search", "query", None)
        }
        (Some("www.mojeek.com"), "/search") => ("www.mojeek.com", "/search", "q", None),
        _ => return false,
    };
    if url.host_str() != Some(host) || url.path() != path {
        return false;
    }
    let pairs: Vec<_> = url.query_pairs().collect();
    let expected_count = if extra_pair.is_some() { 2 } else { 1 };
    if pairs.len() != expected_count
        || pairs[0].0 != query_key
        || pairs[0].1.is_empty()
        || pairs[0].1.len() > MAX_SEARCH_QUERY_BYTES
    {
        return false;
    }
    match extra_pair {
        Some((key, value)) => pairs[1].0 == key && pairs[1].1 == value,
        None => true,
    }
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum ExternalUrlError {
    #[error("external URL is not approved")]
    Refused,
    #[error("the default browser did not accept the URL")]
    OpenFailed,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_fixed_portals_searches_and_hibp_sources() {
        for value in FIXED_PORTALS {
            assert!(validate_external_url(value).is_ok(), "{value}");
        }
        for value in [
            "https://www.google.com/search?q=synthetic%20alias",
            "https://www.bing.com/search?q=synthetic%20alias",
            "https://duckduckgo.com/?q=synthetic%20alias",
            "https://search.brave.com/search?q=synthetic%20alias&source=web",
            "https://www.ecosia.org/search?q=synthetic%20alias",
            "https://www.startpage.com/sp/search?query=synthetic%20alias",
            "https://www.mojeek.com/search?q=synthetic%20alias",
            "https://haveibeenpwned.com/api/v3/breach/SyntheticBreach",
        ] {
            assert!(validate_external_url(value).is_ok(), "{value}");
        }
    }

    #[test]
    fn rejects_credentials_insecure_or_unapproved_destinations_and_parameter_smuggling() {
        for value in [
            "http://www.google.com/search?q=synthetic",
            "https://synthetic:token@127.0.0.1/search?q=synthetic",
            "https://evil.invalid/search?q=synthetic",
            "https://www.google.com.evil.invalid/search?q=synthetic",
            "https://www.google.com/search?q=synthetic&redirect=https%3A%2F%2Fevil.invalid",
            "https://search.brave.com/search?q=synthetic&source=other",
            "https://dehashed.com/?identifier=synthetic",
            "https://haveibeenpwned.com/api/v3/breachedaccount/synthetic",
        ] {
            assert!(validate_external_url(value).is_err(), "{value}");
        }
    }
}

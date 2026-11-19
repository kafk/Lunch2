# Delissimo Gamlestaden

The configured menu URL identifies the restaurant. On each scrape, Lunchdejt
follows the **Gamlestaden** link on the [official homepage](https://delissimo.se/).
Both `Gamle.pdf` and `Gamlestan.pdf` are supported, including when the upload
directory changes. The selected PDF is recorded as `menu_source_url`. The
website link on the menu card points to the stable Delissimo homepage.

The scraper uses the PDF's visual order to match dishes to weekdays. If the
published link is missing or fails, Lunchdejt does not guess the other
filename: it could still point to an older menu. Only a verified backup for
the current week can be used instead.

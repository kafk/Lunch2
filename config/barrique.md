# Barrique lunch menu

The [official lunch page](https://www.barrique.nu/lunch) is the source. Its
wine-list PDF is not a lunch menu and must not be used as a fallback.

The scraper requires a current week label and reads the Swedish and English
menu separately. Shared menu blocks are expanded to their serving days, and
“Det lilla extra” is attached to each dessert's own day. If the layout changes
or the week is stale, Lunchdejt uses only a still-current Barrique lunch cache
or reports the menu as unavailable.

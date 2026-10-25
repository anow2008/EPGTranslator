from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
import gettext
PluginLanguageDomain = 'EPGTranslator'
PluginLanguagePath = 'Extensions/EPGTranslator/locale'

def localeInit():
    gettext.bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))

def _(txt):
    if gettext.dgettext(PluginLanguageDomain, txt):
        return gettext.dgettext(PluginLanguageDomain, txt)
    print('[' + PluginLanguageDomain + '] fallback to default translation for ' + txt)
    return gettext.gettext(txt)

localeInit()
language.addCallback(localeInit)
__version__ = '1.0'

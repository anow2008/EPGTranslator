import re
import time
import os
import json
import traceback
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request, urlopen
from Components.ActionMap import ActionMap, HelpableActionMap
from Components.config import (config, ConfigSubsection, ConfigSelection, ConfigInteger, ConfigBoolean)
from Components.Label import Label
from Components.Language import language
from Components.ScrollLabel import ScrollLabel
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.StaticText import StaticText
from enigma import (eEPGCache, eServiceReference, iPlayableService, iServiceInformation)
from Plugins.Plugin import PluginDescriptor
from Screens.EventView import EventViewBase
from Screens.HelpMenu import HelpableScreen
from Screens.InfoBar import InfoBar
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.VirtualKeyBoard import VirtualKeyBoard
from .AutoflushCache import AutoflushCache
from .HTML5Entities import name2codepoint
from .Skin import MySD
from . import _
EPGTrans_vers = '3.02-release'
dflt_UA = 'OpenVix EPG Translator (Mozilla/5.0 compat): ' + EPGTrans_vers
EPG_OPTIONS = 'BDTSEINX'
ci = 0
for i in range(len(EPG_OPTIONS)):
    if EPG_OPTIONS[i] == 'X':
        continue
    exec('epg_%s = %d' % (EPG_OPTIONS[i], ci))
    ci += 1
epg_PB = ci
langs = [('af', _('Afrikaans')), ('sq', _('Albanian')), ('ar', _('Arabic')), ('az', _('Azerbaijani')), ('eu', _('Basque')), ('be', _('Belarusian')), ('bs', _('Bosnian')), ('bg', _('Bulgarian')), ('ca', _('Catalan')), ('ceb', _('Cebuano')), ('hr', _('Croatian')), ('cs', _('Czech')), ('da', _('Danish')), ('nl', _('Dutch')), ('en', _('English')), ('et', _('Estonian')), ('tl', _('Filipino')), ('fi', _('Finnish')), ('fr', _('French')), ('gl', _('Galician')), ('de', _('German')), ('el', _('Greek')), ('ht', _('Haitian Creole')), ('hu', _('Hungarian')), ('is', _('Icelandic')), ('id', _('Indonesian')), ('ga', _('Irish')), ('it', _('Italian')), ('jw', _('Javanese')), ('lv', _('Latvian')), ('lt', _('Lithuanian')), ('mk', _('Macedonian')), ('ms', _('Malay')), ('mt', _('Maltese')), ('no', _('Norwegian')), ('fa', _('Persian')), ('pl', _('Polish')), ('pt', _('Portuguese')), ('ro', _('Romanian')), ('ru', _('Russian')), ('sr', _('Serbian')), ('sk', _('Slovak')), ('sl', _('Slovenian')), ('es', _('Spanish')), ('sw', _('Swahili')), ('sv', _('Swedish')), ('tr', _('Turkish')), ('uk', _('Ukrainian')), ('ur', _('Urdu')), ('vi', _('Vietnamese')), ('cy', _('Welsh'))]
langs = sorted(langs, key=(lambda x: x[1]))
rtol = {'ar', 'fa', 'ur'}

def get_lang(index):
    for lang in langs:
        if not lang[0] == index:
            continue
        return lang[1]
    return 'Unknown'

config.plugins.translator = ConfigSubsection()
CfgPlTr = config.plugins.translator
CfgPlTr.source = ConfigSelection(default='auto', choices=[('auto', _('Detect Language'))] + langs[:])
CfgPlTr.destination = ConfigSelection(default='en', choices=langs)
CfgPlTr.alternate = ConfigSelection(default='en', choices=langs)
CfgPlTr.start_EV_trans = ConfigBoolean(default=False)
CfgPlTr.timeout_hr = ConfigInteger(0, (0, 350))
CfgPlTr.showsource = ConfigSelection(default='yes', choices=[('yes', _('Yes')), ('no', _('No'))])
CfgPlTr.showtrace = ConfigBoolean(default=False)
curr_dest = CfgPlTr.destination.getValue()
AfCache = AutoflushCache(CfgPlTr.timeout_hr.getValue(), null_return=(None, None))

def applySkinVars(skin, dict):
    for key in list(dict.keys()):
        try:
            skin = skin.replace('{' + key + '}', dict[key])
        except Exception as e:
            print(e, '@key=', key)
            continue
    return skin

def transHTMLEnts(text):
    def repl(ent):
        res = ent.group(0)
        ent = res[1:-1].lower()
        if re.match('#\\d+', ent):
            res = chr(int(ent[1:]))
            return res
        try:
            res = chr(name2codepoint[ent])
        except Exception:
            pass
        return res

    text = re.sub('&.{,30}?;', repl, text)
    return str(text)

GTX_URL = 'https://translate.googleapis.com/translate_a/single'
GTX_UA = 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36'

def PART_translate(enc_text, source, dest):
    # enc_text arrives percent-encoded from DO_translation; decode, then let urlencode re-encode it.
    failed = True
    newtext = ''
    try:
        params = urlencode({'client': 'gtx', 'sl': source, 'tl': dest, 'dt': 't', 'q': unquote(enc_text)})
        headers = {'User-Agent': GTX_UA}
        if len(params) < 1800:
            request = Request(GTX_URL + '?' + params, headers=headers)
        else:
            request = Request(GTX_URL, data=params.encode('utf-8'), headers=headers)
        output = urlopen(request, timeout=20).read().decode('utf-8')
        data = json.loads(output)
        newtext = ''.join(seg[0] for seg in data[0] if seg and seg[0])
        failed = False
    except Exception as e:
        newtext = ''
        print(f'[EPGTranslator-Plugin] PART_translate, {type(e).__name__!s}: "{e!s}"')
        try:
            if CfgPlTr.showtrace.getValue():
                traceback.print_exc()
        except Exception:
            pass
    return failed, newtext

enc_wspace = ''
enc_space = ''
nenc_sep = ''
for c in (' ', '\n', '\t'):
    enc_wspace = enc_wspace + nenc_sep + '\\.' + quote(c)
    enc_space = enc_space + nenc_sep + quote(c)
    nenc_sep = '|'

def DO_translation(text, source, dest):
    for rpl in ('\xc2\x8a', '\xee\x82\x8a'):
        text = text.replace(rpl, '\n')
    enc_text = quote(text)
    enc_len = len(enc_text)
    max = 7000
    nsplit = int(enc_len / max) + 1
    bsize = int(enc_len / nsplit) - 10
    si = 0
    ei = len(enc_text) - 1
    togo = ei
    check_end = True
    res = ''
    while True:
        ri = ei
        if ri > si + bsize:
            ri = si + bsize
        if togo <= max:
            this_encpart = enc_text[si:]
            this_sep = ''
            this_len = len(this_encpart)
        else:
            split_re1 = f'(?:(.{{1,{bsize!s}}})({enc_wspace!s}))'
            split_re1 = re.compile(split_re1)
            match = split_re1.search(enc_text, si, ri)
            if match is None:
                split_re2 = f'(?:(.{{1,{bsize!s}}})({enc_space!s}))'
                split_re2 = re.compile(split_re2)
                match = split_re2.search(enc_text, si, ri)
            if match is None:
                res += '...unable to translate'
                return res.strip()
            this_encpart = match.group(1)
            this_sep = unquote(match.group(2))
            this_len = len(this_encpart) + len(match.group(2))
        failed, this_part = PART_translate(this_encpart, source, dest)
        if failed:
            res += '...unable to translate'
            return res.strip()
        res += this_part + this_sep
        si += this_len
        togo -= this_len
        if togo <= 0:
            return res.strip()
        if check_end and togo < bsize * 2:
            bsize = int(bsize * 2.0 / 3.0)
            check_end = False

sbk_prop = '\\[[^\\]]*\\]'
par_prop = '\\([^\\)]*\\)'
begin_props = f'\n^\\s*                        # Strip any leading whitespace\n(                           # Start all [] + () groups saving\n (?:                        # Start multi-groups\n  (?:(?:{sbk_prop!s}|{par_prop!s})\\s*)          # Either grouping + whitespace\n )*                         # end a group - and repeat\n {sbk_prop!s}                         # last group - []\n)                           # End all () or [] groups saving\n\\s*                         # Skip any intervening whitespace\n(.*)                        # The real description\n\\s*$                        # Strip trailing whitespace to EOL\n'
begin_matcher = re.compile(begin_props, flags=re.X | re.S)
end_props = f'\n^\\s*                        # Strip any leading whitespace\n(.*?)                       # The real description (? else it takes all)\n\\s*                         # Skip any intervening whitespace\n(                           # Start all [] + () groups saving\n {sbk_prop!s}                         # first group - []\n \\s*                        # Skip any intervening whitespace\n (?:                        # Start multi-groups\n  (?:(?:{sbk_prop!s}|{par_prop!s})\\s*)          # Either grouping + whitespace\n )*                         # end a group - and repeat\n (?:\\s*S\\d+\\s*Ep\\d+)?       # UK ITV can have a trailing Sn Epn\n)                           # End all () or [] groups saving\n\\s*$                        # Strip trailing whitespace to EOL\n'
end_matcher = re.compile(end_props, flags=re.X | re.S)
sepline = '**********'

def EPGdata_translate(title, descr, start, duration, uref):
    desc = descr.strip()
    prop = ''
    prepend_props = False
    if len(descr) > 0:
        if '[' in descr[:12]:
            res = re.findall(begin_matcher, descr)
            if len(res) > 0:
                prop, desc = res[0]
                prepend_props = True
        elif ']' in descr[-12:]:
            res = re.findall(end_matcher, descr)
            if len(res) > 0:
                desc, prop = res[0]
    r_text = sepline + '\n' + title + '\n' + sepline + '\n' + desc
    t_text = DO_translation(r_text, CfgPlTr.source.getValue(), curr_dest)
    try:
        t_sep, t_rest = t_text.split('\n', 1)
    except Exception:
        t_sep = 'SPER'
    if re.match('[^*]', t_sep):
        t_title = _('Translation error')
        t_descr = t_text
        return t_title, t_descr
    try:
        t_title, t_descr = t_rest.split('\n' + t_sep + '\n', 1)
        if prop != '' and curr_dest not in rtol:
            if prepend_props:
                t_descr = prop + t_descr
            else:
                t_descr = t_descr + prop
        if start is None:
            to = int(time.time() + 10800)
        else:
            to = int(start + duration + 60 * config.epg.histminutes.getValue())
        if CfgPlTr.timeout_hr.getValue() > 0:
            limit = int(time.time() + 3600 * CfgPlTr.timeout_hr.getValue())
            if limit < to:
                to = limit
        AfCache.add(uref, (t_title, t_descr), abs_timeout=to)
    except Exception as e:
        print(f'[EPGTranslator-Plugin] translateEPG, {type(e).__name__!s}: "{e!s}"')
        if CfgPlTr.showtrace.getValue():
            traceback.print_exc()
        t_title, t_descr = title, descr
    return t_title, t_descr

def make_uref(sv_id, sv_name):
    return ':'.join([curr_dest, str(sv_id), str(sv_name)])

plugin_location = os.path.dirname(os.path.realpath(__file__))

class TranslatorConfig(Setup):
    def __init__(self, session):
        try:
            Setup.__init__(self, session, 'TranslatorConfig', plugin='Extensions/EPGTranslator', PluginLanguageDomain='EPGTranslator')
        except TypeError:
            Setup.__init__(self, session, 'TranslatorConfig', plugin='Extensions/EPGTranslator')
        self.setTitle(_('EPG Translator Setup - ') + EPGTrans_vers)
        CfgPlTr.timeout_hr.addNotifier(self.changeTimeout)

    def keyCancel(self):
        for x in self['config'].list:
            x[1].cancel()
        self.exit()

    def closeRecursive(self):
        self.keyCancel()

    def keySave(self):
        self.saveAll()
        self.exit()

    def exit(self):
        self.session.openWithCallback(self.close, TranslatorMain, None)

    def changeTimeout(self, configElement):
        AfCache.change_timeout(configElement.value)

    def __del__(self):
        CfgPlTr.timeout_hr.removeNotifier(self.changeTimeout)


class TranslatorMain(Screen, HelpableScreen):
    helptext = {}
    base_helptext = '\nInside Plugin:\nLeft <-> Right : <-> +- EPG Event\nOk : enter text to translate\nBouquet : +- Zap\nMenu : Setup\nBlue: Hide screen\nYellow: Clear cache\nRed: Refresh EPG\nBack: Toggle primary/alternate language\n'
    helptext['en'] = base_helptext.strip()
    def __init__(self, session, text):
        self.showsource = CfgPlTr.showsource.getValue()
        if self.showsource == 'yes':
            size = MySD.tmyes
        else:
            size = MySD.tmno
        self.dict = {'size': size, 'plug_loc': plugin_location}
        self.skin = applySkinVars(MySD.TranslatorMain_skin, self.dict)
        self.session = session
        Screen.__init__(self, session)
        HelpableScreen.__init__(self)
        self.text = text
        self.hideflag = True
        self.refresh = False
        self.max = 1
        self.count = 0
        self.list = []
        self.eventName = ''
        self['from_lang'] = Label('')
        self['to_lang'] = Label('')
        self['timing'] = Label('')
        self['u_title'] = Label('')
        self['u_descr'] = ScrollLabel('')
        self['l_title'] = Label('')
        self['l_descr'] = ScrollLabel('')
        if self.showsource != 'yes':
            self['l_title'].hide()
            self['l_descr'].hide()
        AMbindings = {'ok': (self.get_text, _('Access text translator')), 'cancel': (self.exit, _('Close plugin')), 'down': (self.down, _('Scroll translated text down')), 'up': (self.up, _('Scroll translated text up')), 'red': (self.getEPG, _('Refresh EPG')), 'green': (self.showInfo, _('Show plugin info')), 'yellow': (self.clear_cache, _('Clear cache')), 'blue': (self.hideScreen, _('Hide screen')), 'menu': (self.config, _('Access plugin setup')), 'info': (self.showInfo, _('Show plugin info')), 'back': (self.toggle_trans, _('Toggle language'))}
        self.inPlayBack = '0:0:0:0:0:0:0:0:0' in self.My_Sref().toCompareString()
        wintitle = _('EPG Translator')
        try:
            cur_serv = self.My_Sref().getServiceName()
            wintitle += ' - ' + cur_serv
        except Exception:
            pass
        self.setTitle(wintitle)
        if not self.inPlayBack:
            AMbindings.update({'right': (self.rightDown, _('Next EPG event')), 'left': (self.leftUp, _('Previous EPG event')), 'zapdown': (self.zapDown, _('Zap down')), 'zapup': (self.zapUp, _('Zap up'))})
            self.__event_tracker = ServiceEventTracker(screen=self, eventmap={iPlayableService.evTunedIn: self.__serviceTuned})
        self['actions'] = HelpableActionMap(self, ['EPGTranslatorActions'], AMbindings, -1)
        self.onLayoutFinish.append(self.onLayoutFinished)
        self['key_blue'] = StaticText(_('Hide'))
        self['key_yellow'] = StaticText(_('Clear cache'))
        self['key_red'] = StaticText(_('Refresh EPG'))
        self['key_green'] = StaticText(_('Info'))
        self['key_ok'] = StaticText(_('Text input'))
        self['key_back'] = StaticText(_('Toggle language'))
        self['key_menu'] = StaticText(_('MENU'))

    def onLayoutFinished(self):
        source = CfgPlTr.source.getValue()
        if source == 'auto':
            source = _('Original')
        if self.showsource == 'yes':
            self['from_lang'].setText(source)
            dest_w = 'to_lang'
        else:
            dest_w = 'from_lang'
        self[dest_w].setText(get_lang(curr_dest))
        if self.text is None:
            self.getEPG()
            return
        self.translateEPG(self.text, '')

    def __serviceTuned(self):
        wintitle = _('EPG Translator')
        try:
            cur_serv = self.My_Sref().getServiceName()
            wintitle += ' - ' + cur_serv
        except Exception:
            pass
        self.setTitle(wintitle)
        self.getEPG()

    def My_Sref(self):
        service = self.session.nav.getCurrentService()
        info = service.info()
        return eServiceReference(info.getInfoString(iServiceInformation.sServiceref))

    def get_text(self):
        self.session.openWithCallback(self.translateText, VirtualKeyBoard, title=_('Text Translator:'), text='')

    def clear_cache(self):
        AfCache.purge()
        self.session.open(MessageBox, _('Cache cleared'), MessageBox.TYPE_INFO, close_on_any_key=True)

    def translateText(self, text):
        if not text or text == '':
            return
        text = text.strip()
        self.setTitle('Text Translator')
        self['timing'].setText(_('On-line translation'))
        newtext = DO_translation(text, CfgPlTr.source.getValue(), curr_dest)
        self['u_title'].setText('')
        self['l_title'].setText('')
        if self.showsource == 'yes':
            self['u_descr'].setText(text)
            self['l_descr'].setText(newtext)
            return
        self['u_descr'].setText(newtext)
        self['l_descr'].setText('')

    def translateEPG(self, title, descr, do_translate=True):
        if title is None:
            title = ''
        else:
            title = title.strip()
        if descr is None:
            descr = ''
        else:
            descr = descr.strip()
        if title == '' and descr == '':
            return
        try:
            begin = time.strftime('%a %Y-%m-%d %H:%M', time.localtime(int(self.event[epg_B])))
        except Exception:
            begin = ''
        if self.event[epg_D] > 0:
            plen = int(self.event[epg_D]) / 60
            if plen >= 60:
                hr = int(plen / 60)
                plen -= 60 * hr
                duration = '%dh %dm' % (hr, plen)
            else:
                duration = '%dm' % plen
        else:
            duration = ''
        if do_translate:
            uref = make_uref(self.event[epg_I], self.event[epg_N])
            t_title, t_descr = AfCache.fetch(uref)
            if t_descr is None:
                try:
                    start = self.event[epg_PB]
                except Exception:
                    start = self.event[epg_B]
                t_title, t_descr = EPGdata_translate(title, descr, start, self.event[epg_D], uref)
        self['timing'].setText(begin + ' - ' + duration)
        if self.showsource == 'yes':
            self['u_title'].setText(title)
            self['u_descr'].setText(descr)
            self['l_title'].setText(t_title)
            self['l_descr'].setText(t_descr)
            return
        self['u_title'].setText(t_title)
        self['u_descr'].setText(t_descr)
        self['l_title'].setText('')
        self['l_descr'].setText('')

    def getEPG(self):
        self.max = 1
        self.count = 0
        self.list = []
        if self.inPlayBack:
            ssn = self.session.nav
            service = ssn.getCurrentService()
            info = service.info()
            curEvent = info.getEvent(0)
            eventID = None
            short = ''
            extended = 'Description unavailable'
            ename = 'Unknown title'
            Servname = 'Recording'
            dur = 0
            rec_began = None
            play_began = None
            if curEvent:
                try:
                    eventID = curEvent.getEventId()
                except Exception:
                    pass
                try:
                    short = curEvent.getShortDescription()
                except Exception:
                    pass
                try:
                    extended = curEvent.getExtendedDescription()
                except Exception:
                    pass
                try:
                    ename = curEvent.getEventName()
                except Exception:
                    pass
                Servname = ename
                try:
                    dur = curEvent.getDuration()
                except Exception:
                    pass
                try:
                    seek = service.seek()
                    secs_in = seek.getPlayPosition()[1] / 90000
                    play_began = int(time.time() - secs_in)
                except Exception:
                    pass
                try:
                    rec_began = curEvent.getBeginTime()
                except Exception:
                    pass
            if eventID is None:
                try:
                    path = ssn.getCurrentlyPlayingServiceOrGroup().getPath()
                    finfo = os.stat(path)
                    eventID = str(finfo.st_dev) + ':' + str(finfo.st_ino)
                except Exception:
                    eventID = str(int(time.time()))
            pbinfo = [None] * (len(EPG_OPTIONS) - 1)
            pbinfo[epg_I] = eventID
            pbinfo[epg_S] = short
            pbinfo[epg_E] = extended
            pbinfo[epg_T] = ename
            pbinfo[epg_N] = Servname
            pbinfo[epg_D] = dur
            pbinfo[epg_B] = rec_began
            if play_began is not None:
                pbinfo.append(play_began)
            self.list = [tuple(pbinfo)]
        else:
            t_now = int(time.time())
            epg_base = t_now - 60 * int(config.epg.histminutes.getValue())
            epg_extent = 20160
            test = [EPG_OPTIONS, (self.My_Sref().toCompareString(), 0, epg_base, epg_extent)]
            epgcache = eEPGCache.getInstance()
            self.list = epgcache.lookupEvent(test)
            self.max = len(self.list)
            for i in list(range(1, len(self.list))):
                if self.list[i][epg_B] > t_now:
                    break
                self.count = i
        self.showEPG()

    def showEPG(self):
        try:
            self.event = self.list[self.count]
            title = self.event[epg_T]
            short = self.event[epg_S]
            extended = self.event[epg_E]
            self.refresh = False
        except Exception:
            title = 'Press red button to refresh EPG'
            short = ''
            extended = ''
            self.refresh = True
        if short == title:
            short = ''
        if short and extended:
            extended = short + '\n' + extended
        elif short:
            extended = short
        self.translateEPG(title, extended)

    def leftUp(self):
        self.count -= 1
        if self.count == -1:
            self.count = 0
        self.showEPG()

    def rightDown(self):
        self.count += 1
        if self.count == self.max:
            self.count = self.max - 1
        self.showEPG()

    def up(self):
        self['u_descr'].pageUp()
        self['l_descr'].pageUp()

    def down(self):
        self['u_descr'].pageDown()
        self['l_descr'].pageDown()

    def zapUp(self):
        if InfoBar and InfoBar.instance:
            InfoBar.zapUp(InfoBar.instance)

    def zapDown(self):
        if InfoBar and InfoBar.instance:
            InfoBar.zapDown(InfoBar.instance)

    def showInfo(self):
        e2_lang = language.getActiveLanguage().split('_')[0]
        if e2_lang not in self.helptext:
            self.helptext[e2_lang] = DO_translation(self.helptext['en'], 'en', e2_lang)
        text = _('EPG Translator version: ') + EPGTrans_vers + '\n\n' + self.helptext[e2_lang]
        self.session.open(MessageBox, text, MessageBox.TYPE_INFO, close_on_any_key=True)

    def toggle_trans(self):
        global curr_dest
        if curr_dest == CfgPlTr.destination.getValue():
            curr_dest = CfgPlTr.alternate.getValue()
        else:
            curr_dest = CfgPlTr.destination.getValue()
        if self.showsource == 'yes':
            dest_w = 'to_lang'
        else:
            dest_w = 'from_lang'
        self[dest_w].setText(get_lang(curr_dest))
        self.showEPG()

    def config(self):
        self.session.openWithCallback(self.exit, TranslatorConfig)

    def hideScreen(self):
        try:
            with open('/proc/stb/video/alpha', 'w') as f:
                count = 40
                while count >= 0:
                    if self.hideflag:
                        wv = count
                    else:
                        wv = 40 - count
                    f.write('%i' % (config.av.osd_alpha.getValue() * wv / 40))
                    f.flush()
                    count -= 1
        except (IOError, OSError):
            if self.hideflag:
                self.hide()
            else:
                self.show()
        self.hideflag = not self.hideflag

    def exit(self):
        if self.hideflag is False:
            try:
                with open('/proc/stb/video/alpha', 'w') as f:
                    f.write('%i' % config.av.osd_alpha.getValue())
            except (IOError, OSError):
                self.show()
        self.close()


orig_EVB__init__ = None
orig_EVB_setEvent = None

def EPGTr_ToggleMode(self):
    self.EPGTr_translating = not self.EPGTr_translating
    self.setEvent(self.event)

def EPGTr_ToggleView(self):
    global curr_dest
    if curr_dest == CfgPlTr.destination.getValue():
        curr_dest = CfgPlTr.alternate.getValue()
    else:
        curr_dest = CfgPlTr.destination.getValue()
    self.setEvent(self.event)

def My_setEvent(self, event):
    orig_EVB_setEvent(self, event)
    if not self.EPGTr_translating:
        return
    if event is None or not hasattr(event, 'getEventName'):
        return
    uref = make_uref(event.getEventId(), self.currentService.getServiceName())
    t_title, t_descr = AfCache.fetch(uref)
    if t_descr is None:
        title = self.getTitle().strip()
        if 'FullDescription' in self:
            descr = self['FullDescription'].getText().strip()
        else:
            descr = ((event.getShortDescription() or '') + '\n' + (event.getExtendedDescription() or '')).strip()
        t_title, t_descr = EPGdata_translate(title, descr, event.getBeginTime(), event.getDuration(), uref)
    if (curr_dest in rtol) != (CfgPlTr.source.getValue() in rtol):
        sep = '\n'
        t_descr = '\n' + t_descr
    else:
        sep = '\n\n'
    if 'epg_description' in self:
        self['epg_description'].setText(t_title + sep + t_descr)
    if 'epg_eventname' in self:
        self['epg_eventname'].setText(t_title)
    if 'summary_description' in self:
        self['summary_description'].setText(t_descr)
    if 'FullDescription' in self:
        self['FullDescription'].setText(t_descr)
    self.setTitle(t_title)

def My_EVB__init__(self, *args, **kwargs):
    orig_EVB__init__(self, *args, **kwargs)
    which = 'EPGTrans'
    self[which] = ActionMap(['EventViewActions'], {'text': self.EPGTr_ToggleMode, 'back': self.EPGTr_ToggleView})
    self[which].setEnabled(True)
    self['key_text'] = StaticText(_('Toggle translation'))
    self['key_back'] = StaticText(_('Toggle language'))
    self.EPGTr_translating = CfgPlTr.start_EV_trans.getValue()

autostart_init_done = False

def autostart(reason, **kwargs):
    global autostart_init_done, orig_EVB__init__, orig_EVB_setEvent
    if reason != 0:
        return
    if autostart_init_done:
        return
    autostart_init_done = True
    orig_EVB__init__ = EventViewBase.__init__
    EventViewBase.__init__ = My_EVB__init__
    orig_EVB_setEvent = EventViewBase.setEvent
    EventViewBase.setEvent = My_setEvent
    EventViewBase.EPGTr_ToggleMode = EPGTr_ToggleMode
    EventViewBase.EPGTr_ToggleView = EPGTr_ToggleView

def main(session, **kwargs):
    session.open(TranslatorMain, None)

def Plugins(**kwargs):
    return [PluginDescriptor(name=_('EPG Translator'), description=_('Translate your EPG'), where=[PluginDescriptor.WHERE_PLUGINMENU], icon='plugin.png', fnc=main), PluginDescriptor(name=_('EPG Translator'), description=_('Translate your EPG'), where=[PluginDescriptor.WHERE_EXTENSIONSMENU], fnc=main), PluginDescriptor(name=_('EPG Translator'), description=_('Translate your EPG'), where=[PluginDescriptor.WHERE_EVENTINFO], fnc=main), PluginDescriptor(name=_('EPG Translator'), description=_('Translate your EPG'), where=[PluginDescriptor.WHERE_AUTOSTART], fnc=autostart)]


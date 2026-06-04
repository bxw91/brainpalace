# Simple stemmer for Croatian — vendored into BrainPalace.
#
# Algorithm + rule table + transformation table by Nikola Ljubešić and Ivan
# Pandžić (2012), "A Simple Stemmer for Croatian":
#     http://nlp.ffzg.hr/resources/tools/stemmer-for-croatian/
#     (now: https://nlp.ffzg.unizg.hr/resources/tools/stemmer-for-croatian/)
#
# License: Creative Commons Attribution-ShareAlike 3.0 Unported (CC BY-SA 3.0).
# Full license + attribution + the list of modifications made here are recorded
# in vendor/LICENSE-croatian-stemmer (next to this file).
#
# Adaptation by BrainPalace: the upstream `rules.txt` and `transformations.txt`
# data tables were inlined VERBATIM, and the core functions
# (istakniSlogotvornoR / imaSamoglasnik / transformiraj / korjenuj) are kept
# verbatim. The stdin/stdout/file-I/O driver, the `__main__` entry point, and
# the upstream's own inline stop-word handling were stripped. A single-token
# `stem_word(word: str) -> str` entry point was added — BrainPalace tokenizes
# and applies stop-words separately (stopwords_for).
"""Vendored Ljubešić–Pandžić rule-based Croatian stemmer, exposing stem_word()."""
from __future__ import annotations

import re

# --- VERBATIM upstream rules.txt -------------------------------------------
# Each non-comment line is "<stem-pattern> <suffix-alternation>"; comment lines
# start with '#'. Compiled below into ^(stem)(suffix)$ regexes, exactly as the
# upstream read_rules() does.
_RULES_TXT = r"""
.+(s|š)k ijima|ijega|ijemu|ijem|ijim|ijih|ijoj|ijeg|iji|ije|ija|oga|ome|omu|ima|og|om|im|ih|oj|i|e|o|a|u
.+(s|š)tv ima|om|o|a|u
# N
.+(t|m|p|r|g)anij ama|ima|om|a|u|e|i|
.+an inom|ina|inu|ine|ima|in|om|u|i|a|e|
.+in ima|ama|om|a|e|i|u|o|
.+on ovima|ova|ove|ovi|ima|om|a|e|i|u|
.+n ijima|ijega|ijemu|ijeg|ijem|ijim|ijih|ijoj|iji|ije|ija|iju|ima|ome|omu|oga|oj|om|ih|im|og|o|e|a|u|i|
# Ć
.+(a|e|u)ć oga|ome|omu|ega|emu|ima|oj|ih|om|eg|em|og|uh|im|e|a
# G
.+ugov ima|i|e|a
.+ug ama|om|a|e|i|u|o
.+log ama|om|a|u|e|
.+[^eo]g ovima|ama|ovi|ove|ova|om|a|e|i|u|o|
# I
.+(rrar|ott|ss|ll)i jem|ja|ju|o|
# J
.+uj ući|emo|ete|mo|em|eš|e|u|
.+(c|č|ć|đ|l|r)aj evima|evi|eva|eve|ama|ima|em|a|e|i|u|
.+(b|c|d|l|n|m|ž|g|f|p|r|s|t|z)ij ima|ama|om|a|e|i|u|o|
# L
#.+al inom|ina|inu|ine|ima|om|in|i|a|e
#.+[^(lo|ž)]il ima|om|a|e|u|i|
.+[^z]nal ima|ama|om|a|e|i|u|o|
.+ijal ima|ama|om|a|e|i|u|o|
.+ozil ima|om|a|e|u|i|
.+olov ima|i|a|e
.+ol ima|om|a|u|e|i|
# M
.+lem ama|ima|om|a|e|i|u|o|
.+ram ama|om|a|e|i|u|o
#.+(es|e|u)m ama|om|a|e|i|u|o
# R
#.+(a|d|e|o|u)r ama|ima|om|u|a|e|i|
.+(a|d|e|o)r ama|ima|om|u|a|e|i|
# S
.+(e|i)s ima|om|e|a|u
# Š
.+(t|n|j|k|j|t|b|g|v)aš ama|ima|om|em|a|u|i|e|
.+(e|i)š ima|ama|om|em|i|e|a|u|
# T
.+ikat ima|om|a|e|i|u|o|
.+lat ima|om|a|e|i|u|o|
.+et ama|ima|om|a|e|i|u|o|
#.+ot ama|ima|om|a|u|e|i|
.+(e|i|k|o)st ima|ama|om|a|e|i|u|o|
.+išt ima|em|a|e|u
#.+ut ovima|evima|ove|ovi|ova|eve|evi|eva|ima|om|a|u|e|i|
# V
.+ova smo|ste|hu|ti|še|li|la|le|lo|t|h|o
.+(a|e|i)v ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|ama|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|
.+[^dkml]ov ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|
.+(m|l)ov ima|om|a|u|e|i|
# PRIDJEVI
.+el ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|
.+(a|e|š)nj ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|ega|emu|eg|em|im|ih|oj|om|og|a|e|i|o|u
.+čin ama|ome|omu|oga|ima|og|om|im|ih|oj|a|u|i|o|e|
.+roši vši|smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o
.+oš ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|
.+(e|o)vit ijima|ijega|ijemu|ijem|ijim|ijih|ijoj|ijeg|iji|ije|ija|oga|ome|omu|ima|og|om|im|ih|oj|i|e|o|a|u|
#.+tit ijima|ijega|ijemu|ijem|ijim|ijih|ijoj|ijeg|iji|ije|ija|oga|ome|omu|ima|og|om|im|ih|oj|e|o|a|u|i|
.+ast ijima|ijega|ijemu|ijem|ijim|ijih|ijoj|ijeg|iji|ije|ija|oga|ome|omu|ima|og|om|im|ih|oj|i|e|o|a|u|
.+k ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|
# GLAGOLI
.+(e|a|i|u)va jući|smo|ste|jmo|jte|ju|la|le|li|lo|mo|na|ne|ni|no|te|ti|še|hu|h|j|m|n|o|t|v|š|
.+ir ujemo|ujete|ujući|ajući|ivat|ujem|uješ|ujmo|ujte|avši|asmo|aste|ati|amo|ate|aju|aše|ahu|ala|alo|ali|ale|uje|uju|uj|al|an|am|aš|at|ah|ao
.+ač ismo|iste|iti|imo|ite|iše|eći|ila|ilo|ili|ile|ena|eno|eni|ene|io|im|iš|it|ih|en|i|e
.+ača vši|smo|ste|smo|ste|hu|ti|mo|te|še|la|lo|li|le|ju|na|no|ni|ne|o|m|š|t|h|n
#.+ači smo|ste|ti|li|la|lo|le|mo|te|še|m|š|t|h|o|
# Druga_vrsta
.+n uvši|usmo|uste|ući|imo|ite|emo|ete|ula|ulo|ule|uli|uto|uti|uta|em|eš|uo|ut|e|u|i
.+ni vši|smo|ste|ti|mo|te|mo|te|la|lo|le|li|m|š|o
# A
.+((a|r|i|p|e|u)st|[^o]g|ik|uc|oj|aj|lj|ak|ck|čk|šk|uk|nj|im|ar|at|et|št|it|ot|ut|zn|zv)a jući|vši|smo|ste|jmo|jte|jem|mo|te|je|ju|ti|še|hu|la|li|le|lo|na|no|ni|ne|t|h|o|j|n|m|š
.+ur ajući|asmo|aste|ajmo|ajte|amo|ate|aju|ati|aše|ahu|ala|ali|ale|alo|ana|ano|ani|ane|al|at|ah|ao|aj|an|am|aš
.+(a|i|o)staj asmo|aste|ahu|ati|emo|ete|aše|ali|ući|ala|alo|ale|mo|ao|em|eš|at|ah|te|e|u|
.+(b|c|č|ć|d|e|f|g|j|k|n|r|t|u|v)a lama|lima|lom|lu|li|la|le|lo|l
.+(t|č|j|ž|š)aj evima|evi|eva|eve|ama|ima|em|a|e|i|u|
#.+(e|j|k|r|u|v)al ama|ima|om|u|i|a|e|o|
#.+(e|j|k|r|t|u|v)al ih|im
.+([^o]m|ič|nč|uč|b|c|ć|d|đ|h|j|k|l|n|p|r|s|š|v|z|ž)a jući|vši|smo|ste|jmo|jte|mo|te|ju|ti|še|hu|la|li|le|lo|na|no|ni|ne|t|h|o|j|n|m|š
.+(a|i|o)sta dosmo|doste|doše|nemo|demo|nete|dete|nimo|nite|nila|vši|nem|dem|neš|deš|doh|de|ti|ne|nu|du|la|li|lo|le|t|o
.+ta smo|ste|jmo|jte|vši|ti|mo|te|ju|še|la|lo|le|li|na|no|ni|ne|n|j|o|m|š|t|h
.+inj asmo|aste|ati|emo|ete|ali|ala|alo|ale|aše|ahu|em|eš|at|ah|ao
.+as temo|tete|timo|tite|tući|tem|teš|tao|te|li|ti|la|lo|le
# I
.+(elj|ulj|tit|ac|ič|od|oj|et|av|ov)i vši|eći|smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o
.+(tit|jeb|ar|ed|uš|ič)i jemo|jete|jem|ješ|smo|ste|jmo|jte|vši|mo|še|te|ti|ju|je|la|lo|li|le|t|m|š|h|j|o
.+(b|č|d|l|m|p|r|s|š|ž)i jemo|jete|jem|ješ|smo|ste|jmo|jte|vši|mo|lu|še|te|ti|ju|je|la|lo|li|le|t|m|š|h|j|o
.+luč ujete|ujući|ujemo|ujem|uješ|ismo|iste|ujmo|ujte|uje|uju|iše|iti|imo|ite|ila|ilo|ili|ile|ena|eno|eni|ene|uj|io|en|im|iš|it|ih|e|i
.+jeti smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o
.+e lama|lima|lom|lu|li|la|le|lo|l
.+i lama|lima|lom|lu|li|la|le|lo|l
# Pridjev_t
.+at ijega|ijemu|ijima|ijeg|ijem|ijih|ijim|ima|oga|ome|omu|iji|ije|ija|iju|oj|og|om|im|ih|a|u|i|e|o|
# Pridjev
.+et avši|ući|emo|imo|em|eš|e|u|i
.+ ajući|alima|alom|avši|asmo|aste|ajmo|ajte|ivši|amo|ate|aju|ati|aše|ahu|ali|ala|ale|alo|ana|ano|ani|ane|am|aš|at|ah|ao|aj|an
.+ anje|enje|anja|enja|enom|enoj|enog|enim|enih|anom|anoj|anog|anim|anih|eno|ovi|ova|oga|ima|ove|enu|anu|ena|ama
.+ nijega|nijemu|nijima|nijeg|nijem|nijim|nijih|nima|niji|nije|nija|niju|noj|nom|nog|nim|nih|an|na|nu|ni|ne|no
.+ om|og|im|ih|em|oj|an|u|o|i|e|a
"""

# --- VERBATIM upstream transformations.txt ---------------------------------
# Each line is "<from>\t<to>"; a token ending in <from> is rewritten to <to>
# before stemming, exactly as the upstream transformiraj() does.
_TRANSFORMATIONS_TXT = """\
lozi\tloga
lozima\tloga
pjesi\tpjeh
pjesima\tpjeh
vojci\tvojka
bojci\tbojka
jaci\tjak
jacima\tjak
čajan\tčajni
ijeran\tijerni
laran\tlarni
ijesan\tijesni
anjac\tanjca
ajac\tajca
ajaca\tajca
ljaca\tljca
ljac\tljca
ejac\tejca
ejaca\tejca
ojac\tojca
ojaca\tojca
ajaka\tajka
ojaka\tojka
šaca\tšca
šac\tšca
inzima\ting
inzi\ting
tvenici\ttvenik
tetici\ttetika
teticima\ttetika
nstava\tnstva
nicima\tnik
ticima\ttik
zicima\tzik
snici\tsnik
kuse\tkusi
kusan\tkusni
kustava\tkustva
dušan\tdušni
antan\tantni
bilan\tbilni
tilan\ttilni
avilan\tavilni
silan\tsilni
gilan\tgilni
rilan\trilni
nilan\tnilni
alan\talni
ozan\tozni
rave\travi
stavan\tstavni
pravan\tpravni
tivan\ttivni
sivan\tsivni
atan\tatni
cenata\tcenta
denata\tdenta
genata\tgenta
lenata\tlenta
menata\tmenta
jenata\tjenta
venata\tventa
tetan\ttetni
pletan\tpletni
šave\tšavi
manata\tmanta
tanata\ttanta
lanata\tlanta
sanata\tsanta
ačak\tačka
ačaka\tačka
ušak\tuška
atak\tatka
ataka\tatka
atci\tatka
atcima\tatka
etak\tetka
etaka\tetka
itak\titka
itaka\titka
itci\titka
otak\totka
otaka\totka
utak\tutka
utaka\tutka
utci\tutka
utcima\tutka
eskan\teskna
tičan\ttični
ojsci\tojska
esama\tesma
metara\tmetra
centar\tcentra
centara\tcentra
istara\tistra
istar\tistra
ošću\tosti
daba\tdba
čcima\tčka
čci\tčka
mac\tmca
maca\tmca
naca\tnca
nac\tnca
voljan\tvoljni
anaka\tanki
vac\tvca
vaca\tvca
saca\tsca
sac\tsca
naca\tnca
nac\tnca
raca\trca
rac\trca
aoca\talca
alaca\talca
alac\talca
elaca\telca
elac\telca
olaca\tolca
olac\tolca
olce\tolca
njac\tnjca
njaca\tnjca
ekata\tekta
ekat\tekta
izam\tizma
izama\tizma
jebe\tjebi
baci\tbaci
ašan\tašni
"""


def _read_rules(text):
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        osnova, nastavak = line.split(" ")
        yield re.compile(r"^(" + osnova + ")(" + nastavak + r")$")


def _read_transformations(text):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        yield line.split("\t")


rules = list(_read_rules(_RULES_TXT))
transformations = list(_read_transformations(_TRANSFORMATIONS_TXT))


# --- VERBATIM upstream algorithm -------------------------------------------
def istakniSlogotvornoR(niz):
    return re.sub(r"(^|[^aeiou])r($|[^aeiou])", r"\1R\2", niz)


def imaSamoglasnik(niz):
    if re.search(r"[aeiouR]", istakniSlogotvornoR(niz)) is None:
        return False
    else:
        return True


def transformiraj(pojavnica):
    for trazi, zamijeni in transformations:
        if pojavnica.endswith(trazi):
            return pojavnica[: -len(trazi)] + zamijeni
    return pojavnica


def korjenuj(pojavnica):
    for pravilo in rules:
        dioba = pravilo.match(pojavnica)
        if dioba is not None:
            if imaSamoglasnik(dioba.group(1)) and len(dioba.group(1)) > 1:
                return dioba.group(1)
    return pojavnica


def stem_word(word: str) -> str:
    """Stem ONE already-lowercased token.

    Mirrors the upstream single-word path (transformiraj -> korjenuj), with the
    upstream's own stop-word handling removed (BrainPalace applies stopwords
    separately). Words whose matched stem has no vowel or is too short are
    returned unchanged, exactly as korjenuj() leaves them.
    """
    return korjenuj(transformiraj(word))

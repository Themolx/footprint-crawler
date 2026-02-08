#!/usr/bin/env python3
"""
Top Sites Generator - Fetches top websites for any country

This script generates a list of top websites for a specified country by:
1. Downloading the Tranco research list and filtering by country TLD
2. Supplementing with curated country-specific sites
3. Adding global sites popular in the region

Usage:
    python generate_top_sites.py --country cz --count 1000
    python generate_top_sites.py --country sk --count 500
    python generate_top_sites.py --country pl --count 1000
"""

import argparse
import csv
import io
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

# Country configurations with TLDs and curated seed sites
COUNTRY_CONFIGS = {
    "cz": {
        "name": "Czech Republic",
        "tlds": [".cz"],
        "global_sites": [
            # Global sites popular in Czech Republic
            ("google.com", "search"),
            ("youtube.com", "entertainment"),
            ("facebook.com", "social"),
            ("instagram.com", "social"),
            ("twitter.com", "social"),
            ("x.com", "social"),
            ("linkedin.com", "social"),
            ("reddit.com", "social"),
            ("wikipedia.org", "reference"),
            ("tiktok.com", "social"),
            ("whatsapp.com", "communication"),
            ("netflix.com", "entertainment"),
            ("spotify.com", "entertainment"),
            ("amazon.de", "ecommerce"),
            ("ebay.de", "ecommerce"),
            ("aliexpress.com", "ecommerce"),
            ("temu.com", "ecommerce"),
            ("chatgpt.com", "tech"),
            ("openai.com", "tech"),
            ("github.com", "tech"),
            ("booking.com", "travel"),
            ("airbnb.com", "travel"),
        ],
        "curated_sites": {
            # Search & Portals
            "search": ["seznam.cz", "google.cz", "centrum.cz", "atlas.cz"],
            # News
            "news": [
                "novinky.cz", "idnes.cz", "aktualne.cz", "irozhlas.cz", "denik.cz",
                "blesk.cz", "lidovky.cz", "e15.cz", "info.cz", "seznamzpravy.cz",
                "reflex.cz", "respekt.cz", "denikn.cz", "ct24.cz", "ihned.cz",
                "echo24.cz", "forum24.cz", "parlamentnilisty.cz", "tyden.cz",
                "expres.cz", "ahaonline.cz", "denikreferendum.cz", "eurozpravy.cz"
            ],
            # Tech
            "tech": [
                "lupa.cz", "root.cz", "zive.cz", "cnews.cz", "mobilmania.cz",
                "diit.cz", "svetandroida.cz", "jablickar.cz", "letem-svetem-applem.eu",
                "justit.cz", "pctuning.cz", "computerworld.cz", "channelworld.cz"
            ],
            # E-commerce
            "ecommerce": [
                "alza.cz", "mall.cz", "czc.cz", "rohlik.cz", "kosik.cz", "notino.cz",
                "datart.cz", "benu.cz", "tsbohemia.cz", "pilulka.cz", "megapixel.cz",
                "mountfield.cz", "heureka.cz", "zbozi.cz", "srovnanicen.cz",
                "slevomat.cz", "bonami.cz", "okay.cz", "kasa.cz", "elvio.cz",
                "decathlon.cz", "hornbach.cz", "obi.cz", "bauhaus.cz", "ikea.cz",
                "lidl.cz", "kaufland.cz", "billa.cz", "albert.cz", "tesco.cz",
                "penny.cz", "globus.cz", "makro.cz", "dm-drogeriemarkt.cz",
                "rossmann.cz", "fotolab.cz", "proaudio.cz", "muziker.cz",
                "sportisimo.cz", "hervis.cz", "footshop.cz", "bibloo.cz",
                "zoot.cz", "about-you.cz", "answear.cz", "modivo.cz",
                "parfums.cz", "krasa.cz", "dtest.cz", "hledejceny.cz"
            ],
            # Government
            "government": [
                "gov.cz", "mfcr.cz", "cssz.cz", "czso.cz", "justice.cz", "mvcr.cz",
                "mzp.cz", "portal.gov.cz", "mojedatovaschranka.cz", "financnisprava.cz",
                "mpo.cz", "mpsv.cz", "msmt.cz", "mzv.cz", "mzcr.cz", "mmr.cz",
                "md.cz", "mk.cz", "army.cz", "policie.cz", "hrad.cz", "senat.cz",
                "psp.cz", "uoou.cz", "sukl.cz", "ctu.cz", "uhos.cz", "nku.cz",
                "praha.eu", "brno.cz", "ostrava.cz", "plzen.eu", "olomouc.eu"
            ],
            # Finance & Banking
            "finance": [
                "csob.cz", "kb.cz", "csas.cz", "fio.cz", "moneta.cz", "airbank.cz",
                "rb.cz", "equabank.cz", "creditas.cz", "trinity.cz", "mbank.cz",
                "unicreditbank.cz", "oberbank.cz", "ppf.cz", "partners.cz",
                "kurzy.cz", "penize.cz", "mesec.cz", "finance.cz", "finparada.cz",
                "banky.cz", "investicniweb.cz", "roklen.cz", "portu.cz",
                "generali.cz", "allianz.cz", "cpp.cz", "pvzp.cz", "uniqa.cz",
                "kooperativa.cz", "slavia-pojistovna.cz", "pojisteni.cz"
            ],
            # Education
            "education": [
                "cuni.cz", "cvut.cz", "muni.cz", "vutbr.cz", "vscht.cz", "upol.cz",
                "vse.cz", "amu.cz", "famu.cz", "damu.cz", "jamu.cz", "avucr.cz",
                "zcu.cz", "ujep.cz", "osu.cz", "slu.cz", "tul.cz", "uhk.cz",
                "jcu.cz", "mendelu.cz", "vfu.cz", "czu.cz", "utb.cz", "vsb.cz",
                "skrivanek.cz", "jazykovky.cz", "kluby.cz", "eduin.cz",
                "scio.cz", "primaskripta.cz", "ucimesevenku.cz"
            ],
            # Entertainment & Media
            "entertainment": [
                "csfd.cz", "stream.cz", "karaoketexty.cz", "prima.cz",
                "ceskatelevize.cz", "iprima.cz", "nova.cz", "ocko.tv",
                "kinobox.cz", "filmtoro.cz", "sledujufilmy.cz", "ivysilani.cz",
                "voyo.cz", "mall.tv", "skylink.cz", "digi.cz", "o2tv.cz",
                "super.cz", "extra.cz", "ahaonline.cz", "showbiz.cz",
                "onlajny.com", "serialzone.cz", "tvprogram.cz", "mediaguru.cz"
            ],
            # Telecom
            "telecom": [
                "o2.cz", "t-mobile.cz", "vodafone.cz", "cetin.cz",
                "upc.cz", "netbox.cz", "digi.cz", "4ka.cz"
            ],
            # Health
            "health": [
                "ulekare.cz", "lekarna.cz", "drmax.cz", "uzis.cz", "vzp.cz",
                "cpzp.cz", "ozp.cz", "vszp.cz", "rbp.cz", "vozp.cz",
                "zuova.cz", "pfnsp.cz", "vfrn.cz", "fnol.cz", "fnplzen.cz",
                "fnbrno.cz", "fnhk.cz", "fnmotol.cz", "vfn.cz", "uvn.cz",
                "ordinace.cz", "doktori.cz", "zdravi.euro.cz", "onemocneni.cz"
            ],
            # Real Estate & Classifieds
            "classifieds": [
                "sreality.cz", "bezrealitky.cz", "reality.idnes.cz", "realitymix.cz",
                "realingo.cz", "ceskereality.cz", "remax-czech.cz", "mmreality.cz",
                "bazos.cz", "sbazar.cz", "avizo.cz", "annonce.cz", "hyperinzerce.cz"
            ],
            # Jobs
            "jobs": [
                "jobs.cz", "prace.cz", "profesia.cz", "indeed.cz", "startupjobs.cz",
                "dobraprace.cz", "volnamista.cz", "kdejeprace.cz", "monster.cz"
            ],
            # Auto
            "auto": [
                "sauto.cz", "autoesa.cz", "aaaauto.cz", "tipcars.com", "auto.cz",
                "autoweb.cz", "autorevue.cz", "autoforum.cz", "autobazar.eu",
                "autopark.cz", "carsen.cz", "motohouse.cz"
            ],
            # Travel & Transport
            "travel": [
                "ceska-posta.cz", "cd.cz", "idos.cz", "jizdnirady.cz",
                "regiojet.cz", "flixbus.cz", "letuska.cz", "pelikan.cz",
                "invia.cz", "fischer.cz", "cedok.cz", "exim.cz",
                "prague.eu", "kudyznudy.cz", "cestovani.idnes.cz"
            ],
            # Other Services
            "services": [
                "mapy.cz", "firmy.cz", "email.cz", "podnikatel.cz",
                "jakpodnikat.cz", "czec.cz", "epravo.cz", "zakonyprolidi.cz",
                "pravovedeni.cz", "ustavnisoud.cz", "nssoud.cz",
                "pocasi.cz", "yr.no", "meteocentrum.cz", "in-pocasi.cz",
                "akce.cz", "ticketportal.cz", "ticketstream.cz", "goout.net",
                "eventim.cz", "vstupenkydivadla.cz"
            ],
            # Sports
            "sports": [
                "sport.cz", "isport.cz", "livesport.cz", "flashscore.cz",
                "sportrevue.cz", "fotbal.cz", "hokej.cz", "tenis.cz",
                "atletikacr.cz", "cyklistikacr.cz", "plaveanisvaz.cz"
            ],
            # Food & Lifestyle
            "lifestyle": [
                "recepty.cz", "toprecepty.cz", "apetitonline.cz", "fresh.cz",
                "prozeny.cz", "marianne.cz", "elle.cz", "cosmopolitan.cz",
                "harpersbazaar.cz", "forbes.cz", "e-kondice.cz", "vitalia.cz"
            ],
            # Social & Forums
            "social": [
                "lide.cz", "libimseti.cz", "badoo.com", "tinder.com",
                "okoun.cz", "forum.root.cz", "forum.zive.cz"
            ]
        }
    },
    "sk": {
        "name": "Slovakia",
        "tlds": [".sk"],
        "global_sites": [
            ("google.com", "search"),
            ("youtube.com", "entertainment"),
            ("facebook.com", "social"),
            ("instagram.com", "social"),
            ("twitter.com", "social"),
            ("wikipedia.org", "reference"),
            ("tiktok.com", "social"),
            ("netflix.com", "entertainment"),
            ("chatgpt.com", "tech"),
        ],
        "curated_sites": {
            "search": ["google.sk", "zoznam.sk", "azet.sk"],
            "news": [
                "sme.sk", "aktuality.sk", "pravda.sk", "dennikn.sk", "hnonline.sk",
                "ta3.com", "tvnoviny.sk", "cas.sk", "pluska.sk", "topky.sk",
                "teraz.sk", "spravy.rtvs.sk", "startitup.sk", "trend.sk",
                "postoj.sk", "webnoviny.sk", "markiza.sk", "joj.sk"
            ],
            "tech": [
                "zive.sk", "fony.sk", "sector.sk", "mojandroid.sk",
                "dsl.sk", "touchit.sk", "techbox.sk"
            ],
            "ecommerce": [
                "alza.sk", "mall.sk", "heureka.sk", "datart.sk", "nay.sk",
                "okay.sk", "martinus.sk", "notino.sk", "dedoles.sk",
                "lidl.sk", "kaufland.sk", "tesco.sk", "billa.sk",
                "dm-drogeriemarkt.sk", "decathlon.sk", "sportisimo.sk"
            ],
            "government": [
                "gov.sk", "slovensko.sk", "minv.sk", "mfsr.sk", "employment.gov.sk",
                "health.gov.sk", "minedu.sk", "bratislava.sk", "kosice.sk"
            ],
            "finance": [
                "slsp.sk", "vub.sk", "tatrabanka.sk", "csob.sk", "unicreditbank.sk",
                "365bank.sk", "finstat.sk", "peniaze.sk"
            ],
            "education": [
                "uniba.sk", "stuba.sk", "tuke.sk", "upjs.sk", "ukf.sk",
                "ucm.sk", "uniag.sk", "euba.sk"
            ],
            "entertainment": [
                "csfd.sk", "topfilmy.sk", "rtvs.sk", "markiza.sk", "joj.sk"
            ],
            "classifieds": [
                "bazos.sk", "nehnutelnosti.sk", "reality.sk", "topreality.sk"
            ],
            "jobs": [
                "profesia.sk", "kariera.sk", "praca.sk", "pracuj.sk"
            ]
        }
    },
    "pl": {
        "name": "Poland",
        "tlds": [".pl"],
        "global_sites": [
            ("google.com", "search"),
            ("youtube.com", "entertainment"),
            ("facebook.com", "social"),
            ("instagram.com", "social"),
            ("twitter.com", "social"),
            ("wikipedia.org", "reference"),
            ("tiktok.com", "social"),
            ("netflix.com", "entertainment"),
            ("chatgpt.com", "tech"),
            ("allegro.pl", "ecommerce"),
        ],
        "curated_sites": {
            "search": ["google.pl", "onet.pl", "wp.pl", "interia.pl"],
            "news": [
                "onet.pl", "wp.pl", "interia.pl", "gazeta.pl", "tvn24.pl",
                "polsatnews.pl", "rmf24.pl", "natemat.pl", "wyborcza.pl",
                "newsweek.pl", "polityka.pl", "money.pl", "bankier.pl",
                "pb.pl", "pap.pl", "rp.pl", "dziennik.pl", "fakt.pl",
                "se.pl", "pudelek.pl", "plotek.pl"
            ],
            "tech": [
                "dobreprogramy.pl", "antyweb.pl", "bezprawnik.pl",
                "komputerswiat.pl", "benchmark.pl", "chip.pl",
                "instalki.pl", "pclab.pl", "purepc.pl"
            ],
            "ecommerce": [
                "allegro.pl", "ceneo.pl", "x-kom.pl", "morele.net", "mediaexpert.pl",
                "euro.com.pl", "mediamarkt.pl", "rtv-euro-agd.pl", "empik.com",
                "skapiec.pl", "olx.pl", "pepco.pl", "lidl.pl", "biedronka.pl",
                "carrefour.pl", "auchan.pl", "tesco.pl", "rossmann.pl",
                "reserved.com", "zalando.pl", "aboutyou.pl", "modivo.pl",
                "answear.com", "eobuwie.pl", "ccc.pl", "cropp.com", "house.pl"
            ],
            "government": [
                "gov.pl", "sejm.gov.pl", "senat.gov.pl", "prezydent.pl",
                "mf.gov.pl", "mswia.gov.pl", "ms.gov.pl", "men.gov.pl",
                "warszawa.pl", "krakow.pl", "wroclaw.pl", "poznan.pl", "gdansk.pl"
            ],
            "finance": [
                "pkobp.pl", "mbank.pl", "ing.pl", "bzwbk.pl", "millenniumbank.pl",
                "aliorbank.pl", "credit-agricole.pl", "bnpparibas.pl",
                "bankier.pl", "money.pl", "fxmag.pl"
            ],
            "education": [
                "uj.edu.pl", "uw.edu.pl", "pwr.edu.pl", "pw.edu.pl", "agh.edu.pl",
                "put.poznan.pl", "pg.edu.pl", "us.edu.pl", "uam.edu.pl"
            ],
            "entertainment": [
                "filmweb.pl", "cda.pl", "zalukaj.tv", "tvp.pl", "player.pl",
                "ipla.tv", "polsatbox.pl", "hbogo.pl"
            ],
            "classifieds": [
                "olx.pl", "gratka.pl", "otodom.pl", "morizon.pl",
                "domiporta.pl", "nieruchomosci-online.pl"
            ],
            "jobs": [
                "pracuj.pl", "indeed.pl", "praca.pl", "jooble.org",
                "goldenline.pl", "nofluffjobs.com"
            ]
        }
    },
    "de": {
        "name": "Germany",
        "tlds": [".de"],
        "global_sites": [
            ("google.com", "search"),
            ("youtube.com", "entertainment"),
            ("facebook.com", "social"),
            ("instagram.com", "social"),
            ("twitter.com", "social"),
            ("wikipedia.org", "reference"),
            ("amazon.de", "ecommerce"),
        ],
        "curated_sites": {
            "search": ["google.de", "t-online.de", "web.de", "gmx.de"],
            "news": [
                "bild.de", "spiegel.de", "faz.net", "sueddeutsche.de", "welt.de",
                "zeit.de", "focus.de", "stern.de", "tagesschau.de", "n-tv.de",
                "handelsblatt.com", "wiwo.de", "heise.de"
            ],
            "ecommerce": [
                "amazon.de", "ebay.de", "otto.de", "zalando.de", "mediamarkt.de",
                "saturn.de", "idealo.de", "mydealz.de", "lieferando.de",
                "dm.de", "rossmann.de", "lidl.de", "aldi.de", "rewe.de"
            ],
            "government": [
                "bundesregierung.de", "bundestag.de", "bundesrat.de",
                "bmi.bund.de", "bmf.de", "berlin.de", "muenchen.de", "hamburg.de"
            ],
            "finance": [
                "deutsche-bank.de", "commerzbank.de", "sparkasse.de",
                "ing.de", "dkb.de", "n26.com", "finanzen.net", "onvista.de"
            ]
        }
    },
    "at": {
        "name": "Austria",
        "tlds": [".at"],
        "global_sites": [
            ("google.com", "search"),
            ("youtube.com", "entertainment"),
            ("facebook.com", "social"),
        ],
        "curated_sites": {
            "search": ["google.at"],
            "news": [
                "orf.at", "derstandard.at", "diepresse.com", "krone.at",
                "kurier.at", "oe24.at", "heute.at", "salzburg24.at", "vienna.at"
            ],
            "ecommerce": [
                "amazon.at", "willhaben.at", "geizhals.at", "mediamarkt.at",
                "interspar.at", "billa.at", "hofer.at"
            ],
            "government": [
                "oesterreich.gv.at", "bmf.gv.at", "bmi.gv.at", "wien.gv.at"
            ]
        }
    },
    "hu": {
        "name": "Hungary",
        "tlds": [".hu"],
        "global_sites": [
            ("google.com", "search"),
            ("youtube.com", "entertainment"),
            ("facebook.com", "social"),
        ],
        "curated_sites": {
            "search": ["google.hu", "startlap.hu"],
            "news": [
                "index.hu", "hvg.hu", "444.hu", "origo.hu", "portfolio.hu",
                "24.hu", "telex.hu", "blikk.hu", "nlc.hu", "rtl.hu"
            ],
            "ecommerce": [
                "emag.hu", "mediamarkt.hu", "alza.hu", "mall.hu", "extreme-digital.hu",
                "arukereso.hu", "jofogas.hu", "edigital.hu"
            ],
            "government": [
                "kormany.hu", "parlament.hu", "mak.hu", "budapest.hu"
            ]
        }
    }
}

# Tranco list URL - download the latest list
TRANCO_LIST_URL = "https://tranco-list.eu/top-1m.csv.zip"


def download_tranco_list() -> list[tuple[int, str]]:
    """Download the Tranco top sites list and return as [(rank, domain), ...]"""
    print("📥 Downloading Tranco top sites list...")
    
    try:
        req = Request(TRANCO_LIST_URL, headers={'User-Agent': 'TopSitesGenerator/1.0'})
        with urlopen(req, timeout=60) as response:
            zip_data = response.read()
        
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            # The zip contains a single CSV file
            csv_filename = zf.namelist()[0]
            with zf.open(csv_filename) as f:
                csv_content = f.read().decode('utf-8')
        
        domains = []
        for line in csv_content.strip().split('\n'):
            parts = line.split(',')
            if len(parts) >= 2:
                rank = int(parts[0])
                domain = parts[1].strip()
                domains.append((rank, domain))
        
        print(f"   ✓ Downloaded {len(domains):,} domains from Tranco")
        return domains
        
    except URLError as e:
        print(f"   ⚠ Failed to download Tranco list: {e}")
        return []


def filter_by_tld(domains: list[tuple[int, str]], tlds: list[str]) -> list[tuple[int, str]]:
    """Filter domains by country TLDs"""
    filtered = []
    for rank, domain in domains:
        for tld in tlds:
            if domain.endswith(tld):
                filtered.append((rank, domain))
                break
    return filtered


def categorize_domain(domain: str, country_config: dict) -> str:
    """Attempt to categorize a domain based on known patterns"""
    domain_lower = domain.lower()
    
    # Check curated sites first
    for category, sites in country_config.get("curated_sites", {}).items():
        if domain_lower in sites or any(domain_lower.endswith(f".{site}") for site in sites):
            return category
    
    # Heuristic categorization based on domain patterns
    patterns = {
        "news": ["news", "zpravy", "noviny", "denik", "aktual", "info", "24"],
        "ecommerce": ["shop", "store", "eshop", "obchod", "market", "mall", "buy"],
        "government": ["gov", "stat", "min", "urad", "city", "mesto", "obec"],
        "finance": ["bank", "banka", "finance", "pojist", "insur", "credit", "pay"],
        "education": ["uni", "edu", "skol", "vysok", "akadem", "college"],
        "health": ["zdravi", "health", "nemoc", "hospit", "lekar", "pharm", "doctor"],
        "tech": ["tech", "it", "soft", "comp", "digital", "cyber", "dev"],
        "entertainment": ["film", "movie", "tv", "video", "music", "game", "sport"],
        "travel": ["travel", "hotel", "book", "fly", "tour", "trip", "cestn"],
        "social": ["social", "chat", "forum", "commun", "meet", "date"],
    }
    
    for category, keywords in patterns.items():
        if any(kw in domain_lower for kw in keywords):
            return category
    
    return "other"


def generate_top_sites(
    country_code: str,
    count: int = 1000,
    use_tranco: bool = True,
    output_file: Optional[str] = None
) -> list[dict]:
    """
    Generate top sites list for a country.
    
    Args:
        country_code: ISO country code (e.g., 'cz', 'sk', 'pl')
        count: Number of sites to generate
        use_tranco: Whether to fetch from Tranco list
        output_file: Optional output CSV path
    
    Returns:
        List of site dictionaries with url, domain, category, rank
    """
    country_code = country_code.lower()
    
    if country_code not in COUNTRY_CONFIGS:
        available = ", ".join(COUNTRY_CONFIGS.keys())
        raise ValueError(f"Unknown country code: {country_code}. Available: {available}")
    
    config = COUNTRY_CONFIGS[country_code]
    print(f"\n🌐 Generating top {count} sites for {config['name']}...")
    
    sites = {}  # domain -> {url, category, source, rank}
    current_rank = 1
    
    # 1. Add global sites popular in the region (highest priority)
    print("\n📌 Adding global sites...")
    for domain, category in config.get("global_sites", []):
        if domain not in sites:
            sites[domain] = {
                "url": f"https://www.{domain}",
                "domain": domain,
                "category": category,
                "rank": current_rank,
                "source": "global"
            }
            current_rank += 1
    print(f"   ✓ Added {len(config.get('global_sites', []))} global sites")
    
    # 2. Add curated country-specific sites
    print("\n📌 Adding curated sites...")
    curated_count = 0
    for category, domain_list in config.get("curated_sites", {}).items():
        for domain in domain_list:
            if domain not in sites:
                # Determine URL scheme
                if not domain.startswith(('http://', 'https://')):
                    url = f"https://www.{domain}"
                else:
                    url = domain
                    domain = re.sub(r'^https?://(www\.)?', '', url).rstrip('/')
                
                sites[domain] = {
                    "url": url,
                    "domain": domain,
                    "category": category,
                    "rank": current_rank,
                    "source": "curated"
                }
                current_rank += 1
                curated_count += 1
    print(f"   ✓ Added {curated_count} curated sites")
    
    # 3. Fetch from Tranco list and filter by TLD
    if use_tranco and current_rank < count:
        tranco_domains = download_tranco_list()
        filtered_domains = filter_by_tld(tranco_domains, config["tlds"])
        
        print(f"\n📌 Adding {len(filtered_domains)} sites from Tranco ({', '.join(config['tlds'])} TLD)...")
        tranco_added = 0
        for tranco_rank, domain in filtered_domains:
            if domain not in sites and current_rank <= count:
                category = categorize_domain(domain, config)
                sites[domain] = {
                    "url": f"https://www.{domain}",
                    "domain": domain,
                    "category": category,
                    "rank": current_rank,
                    "source": f"tranco:{tranco_rank}"
                }
                current_rank += 1
                tranco_added += 1
        print(f"   ✓ Added {tranco_added} sites from Tranco")
    
    # Convert to sorted list
    result = sorted(sites.values(), key=lambda x: x["rank"])[:count]
    
    # Update ranks to be sequential
    for i, site in enumerate(result, 1):
        site["rank"] = i
    
    print(f"\n✅ Generated {len(result)} sites total")
    
    # Write to CSV if output file specified
    if output_file:
        write_csv(result, output_file)
    
    return result


def write_csv(sites: list[dict], output_file: str):
    """Write sites to CSV file"""
    print(f"\n💾 Writing to {output_file}...")
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['url', 'domain', 'category', 'rank_' + os.path.basename(output_file).split('_')[0]])
        
        for site in sites:
            writer.writerow([
                site['url'],
                site['domain'],
                site['category'],
                site['rank']
            ])
    
    print(f"   ✓ Saved {len(sites)} sites")


def main():
    parser = argparse.ArgumentParser(
        description="Generate top websites list for a country",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --country cz --count 1000
  %(prog)s --country sk --count 500 --output slovak_top_500.csv
  %(prog)s --country pl --count 1000 --no-tranco
        """
    )
    
    parser.add_argument(
        '-c', '--country',
        type=str,
        default='cz',
        choices=list(COUNTRY_CONFIGS.keys()),
        help='Country code (default: cz)'
    )
    parser.add_argument(
        '-n', '--count',
        type=int,
        default=1000,
        help='Number of sites to generate (default: 1000)'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output CSV file path (default: <country>_top_<count>.csv)'
    )
    parser.add_argument(
        '--no-tranco',
        action='store_true',
        help='Skip fetching from Tranco list (use curated only)'
    )
    parser.add_argument(
        '--list-countries',
        action='store_true',
        help='List available countries and exit'
    )
    
    args = parser.parse_args()
    
    if args.list_countries:
        print("\nAvailable countries:")
        for code, config in COUNTRY_CONFIGS.items():
            curated_count = sum(len(sites) for sites in config.get("curated_sites", {}).values())
            print(f"  {code}: {config['name']} ({curated_count} curated sites)")
        return
    
    output_file = args.output or f"{args.country}_top_{args.count}.csv"
    
    # Get the script's directory for output
    script_dir = Path(__file__).parent
    output_path = script_dir / output_file
    
    sites = generate_top_sites(
        country_code=args.country,
        count=args.count,
        use_tranco=not args.no_tranco,
        output_file=str(output_path)
    )
    
    # Print summary
    print(f"\n📊 Summary:")
    categories = {}
    for site in sites:
        cat = site['category']
        categories[cat] = categories.get(cat, 0) + 1
    
    for cat, cnt in sorted(categories.items(), key=lambda x: -x[1])[:10]:
        print(f"   {cat}: {cnt}")


if __name__ == "__main__":
    main()

import pathlib
import tempfile

import httpx

from P2P.Site import Site
from P2P.Ui.UiServer import UiServer
from P2P import compat
from Translate import translate


class TestP2PUiServerTranslate:
    def testHtmlGetsLangParamSubstitutedEvenInDefaultLanguage(self):
        """The harmless part applies unconditionally, even in English --
        translateData()'s own cache-buster token replace, matching the
        original's own always-on behavior."""
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestTranslateLangParamSiteA", pathlib.Path(root))
                await site.storage.write("index.html", b'<script src="all.js?lang={lang}"></script>')

                server = UiServer(sites={"1TestTranslateLangParamSiteA": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            "%s/1TestTranslateLangParamSiteA/index.html?wrapper=0" % base_url
                        )
                        return response.text

        body = compat.run(scenario)
        assert "lang={lang}" not in body
        assert ("lang=%s" % translate.lang) in body

    def testJsUntouchedWhenLanguageIsDefault(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestTranslateJsDefaultSiteA", pathlib.Path(root))
                js = b'console.log("Hello");'
                await site.storage.write("all.js", js)

                server = UiServer(sites={"1TestTranslateJsDefaultSiteA": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            "%s/1TestTranslateJsDefaultSiteA/all.js?wrapper=0" % base_url
                        )
                        return response.content, js

        body, original = compat.run(scenario)
        assert body == original  # No config.language override active -- untouched, matches "en" skip

    def testEligibleHtmlGetsRealPerStringTranslation(self):
        async def scenario():
            original_lang = translate.lang
            translate.lang = "xx"
            try:
                with tempfile.TemporaryDirectory() as root:
                    site = Site("1TestTranslateRealSiteAAAAA", pathlib.Path(root))
                    await site.storage.write("index.html", b"<div>Hello</div>")
                    await site.storage.writeJson("languages/xx.json", {"Hello": "Bonjour"})
                    await site.storage.writeJson("content.json", {"translate": ["index.html"]})
                    await site.content_manager.loadContent("content.json")

                    server = UiServer(sites={"1TestTranslateRealSiteAAAAA": site})
                    async with server.run():
                        base_url = server.bound_addresses[0]
                        async with httpx.AsyncClient() as client:
                            response = await client.get(
                                "%s/1TestTranslateRealSiteAAAAA/index.html?wrapper=0" % base_url
                            )
                            return response.text
            finally:
                translate.lang = original_lang

        body = compat.run(scenario)
        assert "Bonjour" in body
        assert "Hello" not in body

    def testHtmlWithLangFileButNotInTranslateListStaysUntranslated(self):
        """A language file existing on disk isn't enough by itself --
        content.json's own "translate" allowlist has to name the file
        too, matching the original's real opt-in-per-file semantics."""
        async def scenario():
            original_lang = translate.lang
            translate.lang = "xx"
            try:
                with tempfile.TemporaryDirectory() as root:
                    site = Site("1TestTranslateNotListedSiteA", pathlib.Path(root))
                    await site.storage.write("index.html", b"<div>Hello</div>")
                    await site.storage.writeJson("languages/xx.json", {"Hello": "Bonjour"})
                    await site.storage.writeJson("content.json", {"translate": []})  # index.html not listed
                    await site.content_manager.loadContent("content.json")

                    server = UiServer(sites={"1TestTranslateNotListedSiteA": site})
                    async with server.run():
                        base_url = server.bound_addresses[0]
                        async with httpx.AsyncClient() as client:
                            response = await client.get(
                                "%s/1TestTranslateNotListedSiteA/index.html?wrapper=0" % base_url
                            )
                            return response.text
            finally:
                translate.lang = original_lang

        body = compat.run(scenario)
        assert "Hello" in body  # Untouched -- not in content.json's own "translate" list
        assert "Bonjour" not in body

    def testJsGetsRealTranslationWhenEligibleAndNonDefaultLanguage(self):
        async def scenario():
            original_lang = translate.lang
            translate.lang = "xx"
            try:
                with tempfile.TemporaryDirectory() as root:
                    site = Site("1TestTranslateJsRealSiteAAAA", pathlib.Path(root))
                    await site.storage.write("all.js", b'alert("Hello")')
                    await site.storage.writeJson("languages/xx.json", {"Hello": "Bonjour"})
                    await site.storage.writeJson("content.json", {"translate": ["all.js"]})
                    await site.content_manager.loadContent("content.json")

                    server = UiServer(sites={"1TestTranslateJsRealSiteAAAA": site})
                    async with server.run():
                        base_url = server.bound_addresses[0]
                        async with httpx.AsyncClient() as client:
                            response = await client.get(
                                "%s/1TestTranslateJsRealSiteAAAA/all.js?wrapper=0" % base_url
                            )
                            return response.text
            finally:
                translate.lang = original_lang

        body = compat.run(scenario)
        assert '"Bonjour"' in body

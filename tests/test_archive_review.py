import unittest
from news_mvp.editorial import HermesModel, digest


class ArchiveReview(unittest.TestCase):
    def test_image_only_review_preserves_publication_context_and_refuses_text_changes(self):
        class Model(HermesModel):
            def call(self, role, packet, draft=None, **kwargs):
                return {'role':role,'packet':packet,'draft':draft,**kwargs}
        model=Model('unused')
        before={'title':'A dated meeting announcement','image':None}
        after={**before,'image':{'sha256':'a'*64}}
        review={'approved':True,'draft_sha256':digest(before),'reasons':['Original editorial decision']}
        result=model.call_archive_review({},after,before,'2026-09-23T17:44:31+00:00',review)
        self.assertEqual(result['role'],'archive_image_reviewer')
        self.assertEqual(result['context']['original_draft_sha256'],digest(before))
        self.assertEqual(result['context']['original_published_at'],'2026-09-23T17:44:31+00:00')
        self.assertEqual(result['draft'],after)
        self.assertEqual(result['archive_image_only']['original_review_sha256'],digest(review))
        with self.assertRaisesRegex(ValueError,'changed article text'):
            model.call_archive_review({},{**after,'title':'New current reporting'},before,'2026-09-23T17:44:31+00:00',review)
        with self.assertRaisesRegex(ValueError,'original text approval'):
            model.call_archive_review({},after,before,'2026-09-23T17:44:31+00:00',{**review,'approved':False})
        with self.assertRaisesRegex(ValueError,'exact draft'):
            model.call_archive_review({},after,before,'2026-09-23T17:44:31+00:00',{**review,'draft_sha256':'b'*64})

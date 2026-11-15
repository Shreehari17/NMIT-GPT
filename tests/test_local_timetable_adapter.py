"""Fast deterministic tests for the local OCR -> admin response adapter."""
import unittest
from backend.services.timetable_parser.local_pipeline import build_admin_payload,split_content

class LocalAdapterTests(unittest.TestCase):
    def test_lab_code(self):
        self.assertEqual(split_content('22CSL68- A1-L3'), ('22CSL68','A1-L3',True))

    def test_dynamic_period_count_and_class(self):
        ocr = {'complete': True,'period_count':2,'day_names':['Tuesday'],
               'cells':[{'day':'Tuesday','first_slot':1,'last_slot':2,
                        'text':'22CSG73 LAB - PRN+KKK','status':'recognized'}]}
        klass = {'detected_class':'8B','needs_review':False}
        times = {'all_resolved':True,'headers':[
            {'slot':1,'time_slot':'10:00-11:00'},
            {'slot':2,'time_slot':'11:00-12:00'}]}
        result=build_admin_payload(ocr,klass,times)
        self.assertEqual(len(result['rows']),2)
        self.assertEqual(result['rows'][0]['class'],'8B')
        self.assertTrue(result['rows'][1]['is_lab'])
        self.assertEqual(result['rows'][1]['time_slot'],'11:00-12:00')

    def test_unknown_vertical_cell_preserved_for_review(self):
        ocr={'complete':True,'period_count':2,'day_names':['Monday'],
             'cells':[{'day':'Monday','first_slot':1,'last_slot':1,'text':'22CS71','status':'recognized'},
                      {'day':'Monday','first_slot':2,'last_slot':2,'text':'','status':'vertical_merge_review'}]}
        klass={'detected_class':'7A','needs_review':False}
        times={'all_resolved':True,'headers':[{'slot':1,'time_slot':'09:00-09:55'},
                                            {'slot':2,'time_slot':'09:55-10:05'}]}
        result=build_admin_payload(ocr,klass,times)
        self.assertEqual(len(result['rows']),2)
        self.assertIn('[REVIEW REQUIRED:',result['rows'][1]['activity'])
        self.assertTrue(any('edit the REVIEW REQUIRED' in x for x in result['warnings']))


    def test_short_final_period_is_warned_not_modified(self):
        ocr={'complete':True,'period_count':4,'day_names':['Monday'],
             'cells':[{'day':'Monday','first_slot':1,'last_slot':1,'text':'Library','status':'recognized'}]}
        klass={'detected_class':'7A','needs_review':False}
        times={'all_resolved':True,'headers':[
            {'slot':1,'time_slot':'09:00-09:55'},
            {'slot':2,'time_slot':'09:55-10:50'},
            {'slot':3,'time_slot':'10:50-11:45'},
            {'slot':4,'time_slot':'11:45-12:10'}]}
        result=build_admin_payload(ocr,klass,times)
        self.assertTrue(any('unusually short' in w for w in result['warnings']))
        self.assertEqual(result['rows'][0]['time_slot'],'09:00-09:55')

    def test_reject_bad_header_count(self):
        with self.assertRaises(ValueError):
            build_admin_payload({'complete':True,'period_count':2,'cells':[]},
                                {'detected_class':'7A','needs_review':False},
                                {'all_resolved':True,'headers':[]})

if __name__=='__main__':unittest.main()

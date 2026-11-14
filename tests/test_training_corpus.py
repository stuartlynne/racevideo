import unittest
import numpy as np
from tools.make_training_corpus import split_numbers,augment

class TrainingCorpusTests(unittest.TestCase):
 def test_splits_hold_out_real_test_numbers_and_preserve_leading_zeroes(self):
  train,val=split_numbers()
  self.assertFalse(set(train)&set(val));self.assertEqual(len(train)+len(val),1000)
  self.assertNotIn('235',train);self.assertNotIn('469',train)
  self.assertIn('235',val);self.assertIn('469',val)
  self.assertIn('000',train+val);self.assertTrue(all(len(x)==3 for x in train+val))
 def test_seeded_augmentation_is_reproducible_and_does_not_mutate_master(self):
  master=np.full((90,150),255,np.uint8);master[15:75,30:60]=0;original=master.copy()
  first=augment(master,123);second=augment(master,123);other=augment(master,124)
  np.testing.assert_array_equal(first,second);np.testing.assert_array_equal(master,original)
  self.assertFalse(first.shape==other.shape and np.array_equal(first,other))
  self.assertEqual(first.dtype,np.uint8)

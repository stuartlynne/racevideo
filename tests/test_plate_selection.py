import unittest
import numpy as np
import cv2
from racevideo.plate_selection import quality,ViewTracker,consensus,unrotate_quad

class SelectionTests(unittest.TestCase):
 def test_fast_first_step_can_initialize_velocity_without_using_bib(self):
  tracker=ViewTracker(initial_distance_scale=2.5)
  for frame in range(4):tracker.update(frame,[self.detection(frame,20+frame*100)])
  self.assertEqual(len(tracker.tracks),1)
  self.assertEqual(len(tracker.tracks[0].views),4)
 def test_rotated_detector_coordinates_recover_original_pixels(self):
  # Distinct pixel values expose width/height swaps and off-by-one errors.
  original=np.arange(7*11).reshape(7,11)
  for angle in (0,90,180,270):
   rotated=np.rot90(original,angle//90)
   quad=np.array([[0,0],[rotated.shape[1]-1,0],[rotated.shape[1]-1,rotated.shape[0]-1],[0,rotated.shape[0]-1]])
   recovered=unrotate_quad(quad,original.shape,angle)
   for source,(x,y) in zip(quad,recovered):
    self.assertEqual(original[round(y),round(x)],rotated[source[1],source[0]])

 def detection(self,ordinal,x,score=1):
  q=[[x,20],[x+50,20],[x+50,45],[x,45]]
  return dict(ordinal=ordinal,quad=q,quality=dict(score=score,area=1250))
 def test_two_plates_remain_separate_without_reading_numbers(self):
  t=ViewTracker()
  for frame in range(5):t.update(frame,[self.detection(frame,20+frame*8),self.detection(frame,95+frame*8)])
  self.assertEqual(len(t.tracks),2);self.assertEqual([len(x.views) for x in t.tracks],[5,5])
  self.assertLess(np.mean(t.tracks[0].views[-1]['quad'],axis=0)[0],np.mean(t.tracks[1].views[-1]['quad'],axis=0)[0])
 def test_gaps_and_duplicate_preprocessing_detections(self):
  t=ViewTracker(max_gap=3)
  t.update(0,[self.detection(0,20),self.detection(0,21)])
  t.update(1,[self.detection(1,28)]);t.update(5,[self.detection(5,60)])
  self.assertEqual([len(x.views) for x in t.tracks],[2,1])
 def test_selection_is_sharpness_based_and_frame_diverse(self):
  t=ViewTracker()
  for f in range(6):t.update(f,[self.detection(f,20+f*2,score=[1,2,10,9,8,3][f])])
  selected=t.tracks[0].selected(count=3,separation=2)
  self.assertEqual([v['ordinal'] for v in selected],[2,4,0])
 def test_short_traversal_keeps_two_distinct_frames(self):
  t=ViewTracker()
  for f in range(3):t.update(f,[self.detection(f,20+f*2,score=[1,10,2][f])])
  self.assertEqual([v['ordinal'] for v in t.tracks[0].selected()],[1,2])
 def test_sharp_print_beats_blur_and_clipping(self):
  image=np.full((140,250,3),200,np.uint8);cv2.putText(image,'235',(45,92),cv2.FONT_HERSHEY_SIMPLEX,2,(30,30,30),4)
  quad=[[30,30],[210,30],[210,110],[30,110]]
  sharp=quality(image,quad);blur=quality(cv2.GaussianBlur(image,(21,21),5),quad)
  self.assertGreater(sharp['score'],blur['score'])
  self.assertTrue(quality(image,[[0,30],[180,30],[180,110],[0,110]])['clipped'])
 def test_variants_are_not_independent_votes_and_conflicts_remain(self):
  def r(n,f,score=.9):return dict(text=n,ordinal=f,score=score)
  single=consensus([r('235',1),r('235',1)])
  self.assertEqual(single['status'],'candidate');self.assertIsNone(single['number'])
  conflict=consensus([r('609',1),r('906',1),r('609',2),r('906',2)])
  self.assertEqual(conflict['status'],'ambiguous');self.assertIsNone(conflict['number'])
  winner=consensus([r('235',1),r('235',1),r('235',2),r('735',2,.7)])
  self.assertEqual(winner['number'],'235');self.assertEqual(winner['alternatives'][0]['frame_count'],2)

 def test_same_bib_returns_as_a_new_encounter_with_independent_votes(self):
  t=ViewTracker()
  for f in (0,1,2):t.update(f,[self.detection(f,20+f*8)])
  for f in range(3,40):t.update(f,[])
  for f in (40,41,42):t.update(f,[self.detection(f,20+(f-40)*8)])
  self.assertEqual(len(t.tracks),2)
  self.assertEqual(t.tracks[0].end_reason,'detection_gap')
  for track in t.tracks:
   result=consensus([dict(text='235',score=.95,ordinal=v['ordinal']) for v in track.views])
   self.assertEqual(result['number'],'235');self.assertEqual(result['alternatives'][0]['frame_count'],3)
  self.assertEqual(t.tracks[0].views[-1]['ordinal'],2)
  self.assertEqual(t.tracks[1].views[0]['ordinal'],40)
 def test_known_exit_cannot_be_reopened_even_within_gap_tolerance(self):
  t=ViewTracker(max_gap=10)
  t.update(0,[self.detection(0,20)]);t.update(1,[self.detection(1,28)])
  t.close(t.tracks[0].id,2,'left_region')
  t.update(2,[self.detection(2,36)])
  self.assertEqual(len(t.tracks),2);self.assertEqual(len(t.tracks[0].views),2)
 def test_predicted_full_exit_closes_track_without_treating_a_miss_as_exit(self):
  t=ViewTracker(max_gap=10,region_size=(100,80))
  t.update(0,[self.detection(0,55)]);t.update(1,[self.detection(1,75)])
  t.update(2,[])
  self.assertIsNone(t.tracks[0].closed_at) # tail still inside region
  t.update(3,[])
  self.assertEqual(t.tracks[0].end_reason,'left_region')

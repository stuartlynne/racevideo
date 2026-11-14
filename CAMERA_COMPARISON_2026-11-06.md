# ELP listing comparison — November 6, 2026

The user requested inspection through the Chrome extension. The extension returned
open-tab titles/URLs, but all page-content and screenshot calls failed. Public
Amazon/AliExpress page retrieval also failed. The specifications below are verified
manufacturer product-family specifications, not a claim that the exact selected
marketplace variant or current price was verified.

## User-tab references

- Current 4K: https://www.amazon.ca/dp/B0GKGYNDWC
- 4K USB/HDMI,10–55 mm title: https://www.amazon.ca/dp/B0H1J3HMD5
- 5MP global,100-degree lens title: https://www.amazon.ca/dp/B0DHCQ8VJF
- AliExpress 4K IMX678,5–50 mm title: https://www.aliexpress.com/item/1005012199610780.html
- AliExpress 5MP global,10X zoom title: https://www.aliexpress.com/item/1005008646126237.html

AliExpress selected options, marketplace sensor/model IDs and prices remain
unverified. There were two relevant AliExpress tabs, so both are recorded.

## Manufacturer comparison

| Family | Sensor/shutter | Advertised MJPEG modes | Claimed minimum illumination | Lens/output distinction |
|---|---|---|---|---|
| ELP-U3CAM4K60-IB(5-50B), current family |1/1.8-inch Sony IMX678,2.0µm, rolling |3840×2160 at 60 fps over USB3 |0.1lux|5–50 mm manual CS lens; USB3 |
| ELP-USB4KCAM678U3-IB(10-55B), USB/HDMI family |Same IMX678 size/pixels; rolling |3840×2160 at 60 fps; H.264 also listed|0.05lux|10–55 mm manual CS lens;5–50/3.6–10 mm options; USB3 and HDMI |
| ELP-USBGS5MP01-UFV(5-50), older global family |1/2.5-inch OmniVision OG05B10,2.2µm, global|2592×1944 at 50 fps;2592×1440/2560×1440/2304×1296 at 60 fps|0.1lux|USB2; manual varifocal CS lens;100° fixed-lens module is another variant |
| ELP-U3GS05B10C-IB550Y, additional comparison candidate |Same OG05B10 sensor family; global|2592×1944 at 60 fps; YUY2 at 35 fps over USB3|0.1lux|USB3 Type-C;5–50 mm CS lens, with 3.6–10/2.8–12 mm options |

These are advertised modes; actual negotiation, sustained output and shutter
control need physical verification on any new unit. Existing recording tests
used 4K/30. The current camera's advertised 4K/60 remains a separate sustained test.

Sources:

- [Current 4K family](https://www.elpcctv.com/elp-4k-60fps-usb30-camera-large-sensor-imx678-webcam-with-cs-550mm-lens-manual-10x-optical-zoom-p-712.html)
- [USB/HDMI0.05-lux family](https://www.elpcctv.com/elp-118-sony-imx678-sensor-4k-usb30-hdmi-camera-with-cs-1055mm-lens-manual-5x-optical-zoom-p-656.html)
- [USB2 global zoom family](https://www.elpcctv.com/elp-5mp-50fps-global-shutter-usb-camera-with-varifocal-cs-550mm-lens-10x-optical-zoom-p-573.html)
- [100° global module](https://www.elpcctv.com/elp-5mp-50fps-1080p-60fps-global-shutter-usb-camera-module-with-100-degree-no-distortion-lens-p-529.html)
- [USB3 global zoom family](https://www.elpcctv.com/elp-5mp-60fps-global-shutter-usb30-camera-og05b10-sensor-with-cs-550mm-lens-10x-optical-zoom-p-738.html)

## Implications for RaceVideo

The 0.05-lux rating is not proof of a faster lens or a one-stop advantage at our
short exposure. Both 4K families use the same sensor. Their tables do not give
matched exposure, gain, lens aperture or acceptable noise/image-quality conditions
for the lux figures. The HDMI family has a different output/processing board, but
no cause for the lower lux claim is established. Compare actual images at fixed
1/500 or 1/1000 second, matched framing/aperture and controlled gain before treating
that rating as an OCR improvement.

The global-shutter camera is a more meaningful experimental difference: all rows
expose together, removing rolling-shutter geometric distortion. It still blurs
when exposure is too long. Our visible 4 ms motion smear would not disappear simply
by changing shutter type. See [Basler's shutter explanation](https://docs.baslerweb.com/electronic-shutter-types)
and [image-quality guidance](https://docs.baslerweb.com/optimizing-image-quality).

2304×1296 is approximately 3 MP, not the full 5 MP mode. At the same framing it gives
60% of the horizontal and vertical samples of 3840×2160. 2592×1440 offers more detail
at 60 fps in the USB2 family; the full 4:3 mode is 2592×1944 at 50 fps. Mode-dependent
cropping/scaling and field of view remain to be checked on hardware.

The 100° fixed lens is not optically equivalent to a 5–50 mm varifocal lens. A broad
view can leave too few pixels on far-side plates. For an A/B trial, match plate
size/framing rather than compare the two default views. A 10 mm minimum on the
USB/HDMI model also offers less wide-angle flexibility than the current 5 mm lens
for the near/table placement; maximum aperture is not specified in the reviewed
CS-lens tables.

Recommendation: retain the current camera for Sunday's observational trial.
Do not replace it solely for 0.05 versus 0.1 lux. If testing another sensor/shutter,
compare a global-shutter varifocal model; the USB3 full 5 MP/60fps family is worth
checking against the older USB2 listing. Final SKU, lens aperture, exposure controls,
price and delivery need verification before any purchasing decision. No order or
settings change was made.

## Revisit before the 2027 road season: faster fixed lens

November 9 follow-up: defer further lens selection/testing until the project
resumes before road season (March–June). No purchase decision was made.

Gemini suggested a Computar M0814-MP2. Manufacturer specifications identify it as
an **8 mm f/1.4**, manual-focus/manual-iris, 2/3-inch-format C-mount lens; it is
not a 2.8 mm lens. A CS camera requires a 5 mm C-to-CS adapter ring. Computar
lists it as discontinued and rated for 1–1.5 MP imaging:
https://www.computar.com/products/m0814-mp2

An f/2 to f/1.4 change gives approximately one stop more light: in equal lighting
and at equal gain, 1/2500 could become 1/5000 at similar brightness. From f/2.8 to
f/1.4 the theoretical gain is about two stops. Actual transmission matters, and
the current ELP lens's effective aperture at the working zoom/iris setting has
not been established. Do not assume an f/1.4 replacement guarantees an improvement.

Before choosing a replacement:

- Identify the existing lens's maximum/working aperture and focal length.
- Check mounting, adapter clearance, sensor coverage and useful field of view.
- Prefer optics with sufficient resolving performance for the 4K sensor; the
  older Computar rating is a concern for small digits, not a hard camera limit.
- Compare plate sharpness at matched framing, fixed gain and 1/2500 versus 1/5000.
- Test near/middle/far road positions: opening the iris reduces depth of field
  at otherwise matched optical geometry. Wide-open sharpness also needs testing.
- Validate moving riders at road speeds, not only the slow cyclocross examples.

Recheck current availability and specifications when resuming; do not buy based
on this deferred candidate alone.

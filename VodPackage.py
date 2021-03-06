# VOD metadata library. Can generate and manipulate XML files that conform to
# the CableLabs VOD Metadata 1.1 specification
# Copyright 2014 Bo Bayles (bbayles@gmail.com)
# See README for more information
# See LICENSE for license

from lxml import etree
from vod_metadata import check_video, check_picture, md5_checksum, param_skip
import os.path

class MissingElement(Exception):
  pass

class InvalidMpeg(Exception):
  pass

class VodPackage(object):
  # Some metadata attributes can appear more than once in the App_Data sections
  # TODO: Audio_Type is one of these, but this is not implemented yet
  _multiples = {"Provider_Content_Tier", "Subscriber_View_Limit", "Rating",
                "MSORating", "Advisories", "Audience", "Actors", "Director",
                "Producers", "Category", "Genre", "Chapter", "Recording_Artist",
                "Song_Title", "Languages", "Subtitle_Languages",
                "Dubbed_Languages"}
  
  def __init__(self, xml_path):
    self.xml_path = xml_path
    self.tree = etree.parse(self.xml_path)
    ADI = self.tree.getroot()
    
    # The CableLabs VOD Metadata 1.1 specification stores metadata in "AMS" and
    # "App_Data" tags. The files that are part of the package are stored i
    # "Content" tags.
    self.D_ams = {}
    self.D_app = {}
    self.D_content = {}
    
    # Package section
    package_Metadata = ADI.find("Metadata")
    package_AMS = package_Metadata.find("AMS")
    self.D_ams["package"] = package_Metadata.find("AMS").attrib
    self.D_app["package"] = self._parse_App_Data(package_Metadata)
    
    # Title section
    title_Asset = ADI.find("Asset")
    title_Metadata = title_Asset.find("Metadata")
    title_AMS = title_Metadata.find("AMS")
    self.D_ams["title"] = title_Metadata.find("AMS").attrib
    self.D_app["title"] = self._parse_App_Data(title_Metadata)
    
    # Asset elements section: "movie", "poster", and "preview" are supported
    for ae_Asset in title_Asset.findall("Asset"):
      ae_Metadata = ae_Asset.find("Metadata")
      ae_AMS = ae_Metadata.find("AMS")
      ae_type = ae_AMS.attrib["Asset_Class"]
      self.D_ams[ae_type] = ae_AMS.attrib
      self.D_app[ae_type] = self._parse_App_Data(ae_Metadata)
      if ae_Asset.find("Content") is not None:
        self.D_content[ae_type] = ae_Asset.find("Content").attrib["Value"]
    
    self.has_preview = "preview" in self.D_ams
    self.has_poster = "poster" in self.D_ams
    
    self.is_update = self.D_ams["package"]["Version_Major"] != "1"
    self.is_delete = package_AMS.get("Verb", '') == "DELETE"
  
  def _parse_App_Data(self, ae_Metadata):
    D = {}
    for App_Data in ae_Metadata.findall("App_Data"):
      key = App_Data.attrib["Name"]
      value = App_Data.attrib["Value"]
      # Some App_Data fields can occur more than once and are treated as a list
      if key in self._multiples:
        if key in D:
          D[key].append(value)
        else:
          D[key] = [value]
      # Others can only occur once and are treated as plain values
      else:
        D[key] = value
    
    return D
  
  def _write_App_Data(self, ae_type, parent_Metadata):
    for key, value in sorted(self.D_app[ae_type].items(), key=lambda x: x[0]):
      # Configuration controls whether certain values get skipped
      if key in param_skip:
        continue
      # Some of the App_Data tags can be repeated
      if key in self._multiples:
        for v in value:
          ae_App_Data = etree.SubElement(parent_Metadata, "App_Data")
          ae_App_Data.set("App", self.D_ams["package"]["Product"])
          ae_App_Data.set("Name", key)
          ae_App_Data.set("Value", v)
      # Others are only allowed to appear once
      else:
        ae_App_Data = etree.SubElement(parent_Metadata, "App_Data")
        ae_App_Data.set("App", self.D_ams["package"]["Product"])
        ae_App_Data.set("Name", key)
        ae_App_Data.set("Value", value)
  
  def write_xml(self, rewrite=False):
    # A movie element is required by this library
    if "movie" not in self.D_ams:
      raise MissingElement("Package does not specify a movie element")
        
    # Over-write the given XML values with the ones determined by scanning the
    # video if needed
    if rewrite:
      self.check_files()
    
    # Root and doctype
    doctype = '<!DOCTYPE ADI SYSTEM "ADI.DTD">'
    ADI = etree.Element("ADI")
    
    # Package asset
    package_Metadata = etree.SubElement(ADI, "Metadata")
    package_AMS = etree.SubElement(package_Metadata, "AMS")
    for key, value in sorted(self.D_ams["package"].items(), key=lambda x: x[0]):
      package_AMS.set(key, value)
    self._write_App_Data("package", package_Metadata)
  
    # Title asset
    title_Asset = etree.SubElement(ADI, "Asset")
    title_Metadata = etree.SubElement(title_Asset, "Metadata")
    title_AMS = etree.SubElement(title_Metadata, "AMS")
    for key, value in sorted(self.D_ams["title"].items(), key=lambda x: x[0]):
      title_AMS.set(key, value)
    self._write_App_Data("title", title_Metadata)
    
    # Asset elements
    for ae_type in ("movie", "preview", "poster"):
      if ae_type not in self.D_ams:
        continue
      ae_Asset = etree.SubElement(title_Asset, "Asset")
      ae_Metadata = etree.SubElement(ae_Asset, "Metadata")
      # AMS section
      ae_AMS = etree.SubElement(ae_Metadata, "AMS")
      for key, value in sorted(self.D_ams[ae_type].items(), key=lambda x: x[0]):
        ae_AMS.set(key, value)
      self._write_App_Data(ae_type, ae_Metadata)
      # Content element, if it is present
      if ae_type in self.D_content:
        ae_Content = etree.SubElement(ae_Asset, "Content")
        ae_Content.set("Value", self.D_content[ae_type])

    return etree.tostring(ADI, xml_declaration=True, doctype=doctype,
                          encoding='utf-8', pretty_print=True)
  
  def overwrite_xml(self, rewrite=False):
    s = self.write_xml(rewrite)
    with open(self.xml_path, mode="wb") as outfile:
      outfile.write(s)
  
  def files_present(self):
    # Check the referenced content files for existence. If they are all present
    # return True. Otherwise return False.    
    for ae_type, ae_name in self.D_content.items():
      ae_dir = os.path.split(self.xml_path)[0]
      ae_path = os.path.join(ae_dir, ae_name)
      if not os.path.isfile(ae_path):
        return False
    
    return True
  
  def check_files(self):
    for ae_type, ae_name in self.D_content.items():
      # Check to make sure the referenced files exist in the same directory as
      # the XML file
      ae_dir = os.path.split(self.xml_path)[0]
      ae_path = os.path.join(ae_dir, ae_name)
      if not os.path.isfile(ae_path):
        raise MissingElement("Package's {} element is missing - {}".format(ae_type, ae_path))
      # Set the file size and checksum values
      self.D_app[ae_type]["Content_FileSize"] = str(os.path.getsize(ae_path))
      self.D_app[ae_type]["Content_CheckSum"] = md5_checksum(ae_path)
    # For the movie element use MediaInfo to scan the video to determine
    # its bitrate, geometry, etc.
    self._scan_video("movie", ae_path)
    if self.has_preview:
      self._scan_video("preview", ae_path)
    if self.has_poster:
      self._scan_image(ae_path)

  def _remove_ae(self, ae_type):
    try:
      del self.D_ams[ae_type]
      del self.D_app[ae_type]
      del self.D_content[ae_type]
    except KeyError:
      raise MissingElement("Package does not content a {} element".format(ae_type))
  
  def remove_preview(self):
    self._remove_ae("preview")
    self.has_preview = False
  
  def remove_poster(self):
    self._remove_ae("poster")
    self.has_poster = False
  
  def make_update(self):
    for ae_type in self.D_ams:
      new_version = int(self.D_ams[ae_type]["Version_Major"]) + 1
      self.D_ams[ae_type]["Version_Major"] = str(new_version)
    
    # The Content element shouldn't be present for updates, per section 8.1
    # of the ADI spec.  
    self.D_content = {}
    self.is_update = True

  def make_delete(self):
    for ae_type in self.D_ams:
      self.D_ams[ae_type]["Verb"] = "DELETE"
    
    self.is_delete = True
  
  def _scan_video(self, ae_type, ae_path):
    mpeg_info = check_video(ae_path)
    
    # Calculate the run time of the video
    duration_s = round(float(mpeg_info["General"]["Duration"]) / 1000)
    duration_h, duration_s = divmod(duration_s, 3600)
    duration_m, duration_s = divmod(duration_s, 60)
    duration_h = format(duration_h, "02")
    duration_m = format(duration_m, "02")
    duration_s = format(duration_s, "02")
    # For the movie asset, the Run_Time and Display_Run_Time are given as part
    # of the title's metadata. For the preview asset, the Run_Time is given
    # as part of the preview's metadata
    if ae_type == "movie":
      self.D_app["title"]["Run_Time"] = "{}:{}:{}".format(duration_h, duration_m, duration_s)
      self.D_app["title"]["Display_Run_Time"] = "{}:{}".format(duration_h, duration_m)
    elif ae_type == "preview":
      self.D_app["preview"]["Run_Time"] = "{}:{}:{}".format(duration_h, duration_m, duration_s)
    
    # Determine the movie's codec
    commercial_name = mpeg_info["Video"]["Commercial name"]
    format_profile = mpeg_info["Video"]["Format profile"]
    if commercial_name == "MPEG-2 Video":
      self.D_app[ae_type]["Codec"] = "MPEG2"
    elif commercial_name == "AVC":
      avc_profile = format_profile[0]
      avc_level = format_profile[format_profile.find("@"):].replace(".", "")
      self.D_app[ae_type]["Codec"] = "AVC {}P{}".format(avc_profile, avc_level)
    else:
      raise InvalidMpeg("Could not determine codec for {}".format(self.D_content[ae_type]))
    
    # Determine the audio type
    audio_type = int(mpeg_info["Audio"].get("Channel(s)", 0))
    self.D_app[ae_type]["Audio_Type"] = "Stereo" if  audio_type > 1 else "Mono"
    
    # Determine the geometry
    movie_resolution_height = mpeg_info["Video"]["Height"]
    move_resolution_scan = mpeg_info["Video"]["Scan type"][0].lower()
    self.D_app[ae_type]["Resolution"] = "{}{}".format(movie_resolution_height, move_resolution_scan)
    
    # Determine the movie's frame rate and bitrate (actually kilobit rate)
    self.D_app[ae_type]["Frame_Rate"] = str(round(float(mpeg_info["Video"]["Frame rate"])))
    self.D_app[ae_type]["Bit_Rate"] = str(round(float(mpeg_info["General"]["Overall bit rate"]) / 1000))

  def _scan_image(self, ae_path):
    img_info = check_picture(ae_path)
    img_width = img_info["Image"]["Width"]
    img_height = img_info["Image"]["Height"]
    self.D_app["poster"]["Image_Aspect_Ratio"] = "{}x{}".format(img_width, img_height)
  
  def list_files(self):
    package_pid = self.D_ams["package"]["Provider_ID"]
    package_paid = self.D_ams["package"]["Asset_ID"]
    title_pid = self.D_ams["title"]["Provider_ID"]
    title_paid = self.D_ams["title"]["Asset_ID"]
    movie_pid = self.D_ams["movie"]["Provider_ID"] if "movie" in self.D_ams else ''
    movie_paid = self.D_ams["movie"]["Asset_ID"] if "movie" in self.D_ams else ''
    movie_file = self.D_content["movie"] if "movie" in self.D_content else ''
    preview_pid = self.D_ams["preview"]["Provider_ID"] if self.has_preview else ''
    preview_paid = self.D_ams["preview"]["Asset_ID"] if self.has_preview else ''
    preview_file = self.D_content["preview"] if self.has_preview else ''
    poster_pid = self.D_ams["poster"]["Provider_ID"] if self.has_poster else ''
    poster_paid = self.D_ams["poster"]["Asset_ID"] if self.has_poster else ''
    poster_file = self.D_content["poster"] if self.has_poster else ''
    
    return (package_pid, package_paid,
            title_pid, title_paid,
            movie_pid, movie_paid, movie_file,
            preview_pid, preview_paid, preview_file,
            poster_pid, poster_paid, poster_file)
# VOD metadata file generator - md5_checksum sub-module
# Copyright 2013 Bo Bayles (bbayles@gmail.com)
# See README for more information
# See LICENSE for license
import hashlib

def md5_checksum(file_path, chunk_bytes=163840):
  """Return the MD5 checksum (hex digest) of the file"""
  
  with open(file_path, "rb") as infile:
    checksum = hashlib.md5()
    while 1:
      data = infile.read(chunk_bytes)
      if not data:
        break
      checksum.update(data)
  
  return checksum.hexdigest()
# Copyright (C) 2018-2026 by xcentaurix
# License: GNU General Public License v3.0


instance = None


class FileManager():
    def __init__(self):
        return

    @staticmethod
    def getInstance():
        global instance  # pylint: disable=global-statement
        if not instance:
            instance = FileManager()
        return instance

    def archive(self, _callback=None):
        return

    def purgeTrashcan(self, _retention=0, _callback=None):
        return

    def cancelJobs(self):
        return

import re
import os


def convert_actual_path_to_virtual(path):
    asset_index = path.find("assets")
    tmp_idx = path.find("tmp")

    if re.search("http", path):
        return path

    elif asset_index != -1:
        return path[asset_index:]

    elif tmp_idx != -1:
        return path[tmp_idx + 4 :]

    else:
        return path

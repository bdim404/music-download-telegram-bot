def sanitize(name, replace_with=""):
    clean_up_list = ["\\", "/", ":", "*", "?", '"', "<", ">", "|", "\0", "$", "\""]
    for x in clean_up_list:
        name = name.replace(x, replace_with)
    return name
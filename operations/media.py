import hashlib


def digest(storage, name):
    value = hashlib.sha256()
    with storage.open(name, "rb") as file:
        for chunk in file.chunks():
            value.update(chunk)
    return value.hexdigest()


def copy_verified(source, destination, name):
    expected = digest(source, name)
    if destination.exists(name):
        if digest(destination, name) != expected:
            raise ValueError("Existing object has different contents: " + name)
        return False
    with source.open(name, "rb") as file:
        saved = destination.save(name, file)
    if saved != name or digest(destination, saved) != expected:
        raise ValueError("Copy verification failed: " + name)
    return True

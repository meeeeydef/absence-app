import getpass
from .main import set_admin
if __name__ == '__main__':
    username = input('Identifiant administrateur : ').strip()
    password = getpass.getpass('Mot de passe (12 caractères minimum) : ')
    if password != getpass.getpass('Confirmer : '):
        raise SystemExit('Les mots de passe ne correspondent pas.')
    set_admin(username, password)
    print('Compte unique configuré. Les anciennes sessions sont révoquées.')

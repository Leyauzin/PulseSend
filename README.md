Installation
Cloner le projet
git clone <URL_DE_TON_PROJET>
cd PulseSend
Installer les dépendances
pip install -r requirements.txt

Cette commande installe toutes les librairies nécessaires pour faire tourner l’application.

Lancer l’application
Option 1 – Directement en Python
python App.py

Lance Pulse Send en mode script.

Option 2 – Compiler en exécutable
pyinstaller --onefile App.py

Crée un fichier .exe autonome dans le dossier dist/.

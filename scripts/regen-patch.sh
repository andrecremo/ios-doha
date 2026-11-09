set -e
W=~/doha-xnu/willow-doha
R=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
S=$R/scripts
cd $W
git status --short | head
git reset -q --hard 796e42b
python3 $S/doha_willow_edit.py $W
git add -A xnuloader xnu/files xnu/redwood.patch
git -c user.name="andrecremo" -c user.email="andreljsantos@gmail.com" commit -q -m "doha: a platform of its own (SM6125, 1080 x 2280)"
git format-patch -1 --stdout > $R/willow/patches/0001-doha.patch
git log --oneline -1
cp -a xnu/files/. xnu-src/xnu-8796.121.2/
grep -c platform_doha xnuloader/loader.c

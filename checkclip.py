"""
ПРОВЕРКА ВВОДА В КОНСОЛИ — доходит ли пароль до сервера без потерь.

Зачем: VNC-консоль Aeza не передаёт Shift, поэтому заглавные буквы и символы
вроде «_» или «!» могут пропасть по дороге — и правильный пароль сервер увидит
как неправильный. Скрипт НИЧЕГО не показывает и никуда не сохраняет: только
считает, сколько символов какого вида пришло. Сверьте цифры со своим паролем.

Запуск:  cd /root/recon && python3 checkclip.py
"""
import getpass

s = getpass.getpass("Вставьте или наберите пароль (на экране не видно), затем Enter: ")

upper = sum(1 for c in s if c.isalpha() and c.isupper())
lower = sum(1 for c in s if c.isalpha() and c.islower())
digits = sum(1 for c in s if c.isdigit())
other = len(s) - upper - lower - digits
nonascii = sum(1 for c in s if ord(c) > 127)

print()
print("Сервер получил:")
print(f"  всего символов: {len(s)}")
print(f"  заглавных букв: {upper}")
print(f"  строчных букв:  {lower}")
print(f"  цифр:           {digits}")
print(f"  прочих знаков:  {other}")
if nonascii:
    print(f"  ⚠ не-латинских символов: {nonascii}")
print()
if len(s) == 0:
    print("Ничего не пришло — вставка не сработала.")
elif upper == 0:
    print("Заглавных нет. Если в пароле они есть — консоль их теряет,")
    print("вход этим способом не пройдёт (см. подсказку в чате).")
else:
    print("Заглавные дошли — значит ввод не искажается, дело в самом пароле.")

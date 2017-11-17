from django.shortcuts import render
from wallet.models import *
from wallet.decorators import *
from wallet.utility import *
from payment_gateway.utility import *
from game_center.models import *
from django.views.decorators.csrf import csrf_exempt 
from wallet.RedisConnector import RedisConnector
from wallet.PhoneNumberVerificator import PhoneNumberVerificator
import time
from datetime import datetime, timedelta, time as asia_time
from wallet.models import *
# Create your views here.
global connect
connect = RedisConnector()
global pnv
pnv = PhoneNumberVerificator()
@csrf_exempt
@login_required
def game_info(request, profile):
    if request.method == 'GET':
        req = request.GET
    else:
        req = json.loads(request.body.decode())
    play_game = game.objects.get(game=req.get('game')) 
    #print(req)
    query = get_q(
        'AND',
        user=profile,
        game=play_game,
    )
    gamers = player.objects.filter(query) 
    if len(gamers) == 0:
        if play_game.id == 3 and 'dexus' not in profile.allowed_operation:
            return '459', '该账号暂未获得体验资格', 'none'
        gamer = player.objects.create(
            user=profile,
            point = 0,
            game=play_game
        )
    else:
        gamer = gamers[0]
    # active的状态分别为: 0-下线/暂停，1-在线
    if gamer.active == '0':
        #记录进入时间
        gamer.start_stamp = str(time.time()) 
        gamer.active = '1'
        total_frequency = int(gamer.total_frequency)
        gamer.total_frequency = str(total_frequency + 1)
        player_operation.objects.create(
            operation='1',
            game = play_game,
            player=gamer
        )
    if request.method == 'PUT':    
        gamer.point = str(req.get('point'))
    # 如果玩家下线或暂离    
    if request.method == 'DELETE':    
        gamer.active='0'
        now_stamp = time.time()
        start_stamp = float(gamer.start_stamp)
        total_stamp = float(gamer.total_time)
        total_time = now_stamp - start_stamp + total_stamp
        gamer.total_time = str(total_time)
        gamer.save()
        player_operation.objects.create(
            operation='0',
            game = play_game,
            player=gamer
        )
        return '200', '退出成功', 'none'
    gamer.save()
    game_info = {
        'point': gamer.point,
        'conversion': eval(play_game.conversion),
        'opportunity': eval(play_game.opportunity)
    }
    return '200', 'success', game_info

@check_method('PUT')
@login_required
def points(request, profile):
    req = json.loads(request.body.decode())
    operation = req['operation']
    play_game = game.objects.get(game=req.get('game')) 
    gamer = player.objects.get(user=profile, game=play_game)
    amount = int(req.get('amount'))
    balances = Balance.objects.filter(currency_name='vr9', owner=profile)
    if len(balances) == 0:
        balance = Balance.objects.create(
            currency_name='vr9',
            amount='0',
            owner=profile
        )
    else:
        balance = balances[0]
    query = get_q(
        'AND',
        user=profile,
        game=play_game,
    )
    gamers = player.objects.filter(query) 
    if len(gamers) == 0:
        #if play_game.id == 2:
        #    return '459', '还在内测中,稍后开放', 'none'
        gamer = player.objects.create(
            user=profile,
            point = 0,
            game=play_game
        )
    else:
        gamer = gamers[0]
    conversion = eval(play_game.conversion)
    # 如果是把积分兑换为vr9
    if operation == 'withdraw':
        #return '505', '接口出现错误', 'none'
        point = amount * int(conversion['points_vr9'])
        if point > int(gamer.point):
            vr9 = str(int(gamer.point) / conversion['points_vr9'])
            return '400', '最多兑换%s' % vr9, 'none'
        if amount < 0 :
            return '401', '请输入正数', 'none'
        if amount > 10:
            return '419', '一天最多能兑换10个币', 'none'
        # 判断是否达到每日限额
        today = datetime.now().date()
        tomorrow = today + timedelta(1)
        today_start = datetime.combine(today, asia_time())
        today_end = datetime.combine(tomorrow, asia_time())
        operation_list = player_operation.objects.filter(
            operation_time__range = (today_start,today_end),
            operation = '3',
            player = gamer
        )
        total = 0
        for t in operation_list:
            total += int(t.amount)
        if total + amount > 10:
            return '416', '您今日已经兑换%s个币, 最多还能兑换%s个币' % (
                str(total),str(10-total)), 'none'
        gamer.point = str(int(gamer.point) - point)
        gamer.point_output = str(int(gamer.point_output) + point)
        gamer.vr9_input = str(int(gamer.vr9_input) + amount)
        gamer.save()
        balance.amount = str(float(balance.amount) + amount)
        balance.save()
        payment = Payment.objects.create(
                operation_type='20',
                currency_name='vr9',
                amount=str(amount),
                user=profile,
                pay_info='用积分%s兑换%svr9币' % (
                    str(point),
                    str(amount)
                )
            )
        player_operation.objects.create(
            operation='3',
            amount=amount,
            points=point,
            game = play_game,
            player=gamer
        )
        return '200', '游戏积分兑换vr积分成功', 'none'
    # 或者把vr9充值为积分
    elif operation == 'charge':
        balance_type, referer_id, referer_from =\
                'vr9', profile.mobile, 'game_center'
        if amount < 0 :
            return '404', '请输入正数', 'none'
        if amount > 999:
            return '405', '兑换的vr9币不能超过999'
        status, message, gap= profile.get_balance(
            balance_type).check_balance(amount,balance_type)
        if status == '200':
            # 如果差额大于0说明发生了预存订单,余额发生变化，需要重新取
            if gap > 0:
                balance = profile.get_balance(balance_type)
        else:
            return '403', '您当前支付方式额度不足', 'none'
        point = amount * int(conversion['vr9_points'])
        gamer.point = str(int(gamer.point) + point)
        gamer.point_input = str(int(gamer.point_input) + point)
        gamer.vr9_output = str(int(gamer.vr9_output) + amount)
        gamer.save()
        balance.amount = str(float(balance.amount) - amount)
        balance.save()
        payment = Payment.objects.create(
                operation_type='19',
                currency_name='vr9',
                amount = str(amount),
                user=profile,
                pay_info='用%svr9币兑换%s积分' % (
                    str(amount),
                    point 
                )
            )
        player_operation.objects.create(
            operation='4',
            amount=amount,
            points=point,
            game = play_game,
            player=gamer
        )
        return '200', 'vr积分兑换游戏积分成功', 'none'
    else:
        pass

# --------------------------游戏道具商城------------
#用户操作对道具的操作
@login_required
def commodity(request, profile):
    if request.method == 'GET':
        return get_comd(request, profile)
    elif request.method == 'POST':
        return pay_comd(request, profile)
    elif request.method == 'PUT':
        return use_comd(request, profile)
    else:
        return '400', '请求错误', 'none'
#得到商品信息
def get_comd(request, profile):
    #import pdb;pdb.set_trace()
    cate_name = request.GET.get('name')
    print(cate_name)
    #list_name = [_.name for _ in Category.objects.all()]
    player_obj = player.objects.get(user=profile, game_id='2')
    if  cate_name == 'avatar_frame':
        cate_id = Category.objects.get(name = cate_name).id
        comds = Commodity.objects.filter(category_id = cate_id).order_by('id')
        cate_obj = Category.objects.get(id = cate_id)
        comds_info = []
        comd = [i for i in comds]
        for i in range(len(comd)):
            content = {
                'name' : comd[i].name,
                'price' : comd[i].price, 
                'type' : comd[i].img_type
            }
            comds_info.append(content)
        return '200', '查询成功', {'comds_info':comds_info, 'expire':cate_obj.expire, 'vr':player_obj.point}
    elif cate_name == 'avatar_shop':
        cate_id = Category.objects.get(name = cate_name).id
        comds = Commodity.objects.filter(category_id = cate_id).order_by('id')
        cate_obj = Category.objects.get(id = cate_id)
        comds_info = []
        comd = [i for i in comds]
        for i in range(len(comd)):
            content = {
                'name' : comd[i].name,
                'price' : comd[i].price,
                'type' : comd[i].img_type
            }
            comds_info.append(content)
        return '200', '查询成功', {'comds_info':comds_info, 'expire':cate_obj.expire, 'vr':player_obj.point}
    elif cate_name == 'theme':
        comds_info = []
        cate_obj = Category.objects.get(id = '3')
        tables = Commodity.objects.filter(category_id='3').order_by('id')
        cards = Commodity.objects.filter(category_id='5').order_by('id')
        table = [i for i in tables]
        card = [i for i in cards]
        for i in range(len(table)):
            content = {
                'name': table[i].name,
                'price': table[i].price,
                'type': table[i].img_type
            }
            comds_info.append(content)
        for i in range(len(card)):
            content = {
                'name': card[i].name,
                'price': card[i].price,
                'type': card[i].img_type
            }
            comds_info.append(content)
        return '200', '查询成功', {'comds_info':comds_info, 'expire':cate_obj.expire, 'vr':player_obj.point}
    else:
        #import pdb;pdb.set_trace()
        comds = Purchased.objects.filter(user=profile).order_by('id')
        comds_info = []
        comd = [i for i in comds]
        #获取已购买商品信息
        for i in range(len(comd)):
            print(comd[i].comd_name)
            phd_time  = utc2local(comd[i].purchase_time)
            phd_time = phd_time.replace(tzinfo=None)
            print(phd_time)
            nowtime = datetime.now()
            print(nowtime)
            #判断道具是否过期，过期就不返回给用户
            expire_minus = comd[i].comd_expire - (nowtime - phd_time).days
            print((nowtime - phd_time).days)
            print(expire_minus)
            if expire_minus == 0:
                remain_time = '小于一天'
                content = {
                    'name': comd[i].comd_name,
                    'status': comd[i].status,
                    'expire': remain_time
                }
                comds_info.append(content)
            elif expire_minus > 0:
                remain_time = expire_minus
                content = {
                    'name': comd[i].comd_name,
                    'status': comd[i].status,
                    'expire': remain_time
                }
                comds_info.append(content)
            else:
                pass
        return '200', '查询成功', {'comds_info':comds_info, 'vr':player_obj.point}

#购买商品
def pay_comd(request, profile):
    #import pdb;pdb.set_trace()
    req = json.loads(request.body.decode())
    comd_data = req['name']
    print(comd_data)
    player_obj = player.objects.get(user=profile, game_id='2')
    #import pdb;pdb.set_trace()
    try:
        shop = Commodity.objects.get(name = comd_data)
    except:
        return '404', '您输入的商品不存在', 'none'
    #datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    list_name =[_.comd_name for _ in Purchased.objects.filter(user=profile)]
    #购买商品
    if comd_data not in list_name:
        if shop.price > float(player_obj.point):
            return '203', '您的积分余额不足', 'none'
        #if shop.price <= player_obj.point:
        else:
            player_obj.point = float(player_obj.point) - shop.price
            #加入到购买记录
            purchased = Purchased.objects.create(
                comd_name = shop.name,
                comd_expire = shop.expire,
                comd_img_type = shop.img_type,
                category_id = shop.category_id,
                user = profile 
            )
            purchased.save()
            player_obj.save()
            return '200', '购买成功', {'剩余积分':player_obj.point}
    #重复购买
    else:
        if shop.price > float(player_obj.point):
            return '203', '您的积分余额不足', 'none'
        else:
            player_obj.point = float(player_obj.point) - shop.price
            player_obj.save()
            #判断道具是否过期，根据过期时间更新有效期
            purchased = Purchased.objects.get(user=profile, comd_name=comd_data)
            phd_time  = utc2local(purchased.purchase_time)
            phd_time = phd_time.replace(tzinfo=None)
            print(phd_time)
            nowtime = datetime.now()
            print(nowtime)
            expire_minus = purchased.comd_expire - (nowtime - phd_time).days
            print((nowtime - phd_time).days)
            print(expire_minus)
            #道具还未过期，购买时间不变，有效期更新为商品已有的有效期加上商品有效期π
            if expire_minus >= 0:
                purchased.comd_expire = purchased.comd_expire + shop.expire
                purchased.save()
            #道具已过期，购买时间从当前开始，有效期更新为商品有效期
            else:
                purchased.purchase_time = nowtime
                purchased.comd_expire = shop.expire
                purchased.save()
        return '200', '购买成功', {'剩余积分': player_obj.point}

#装备道具

def use_comd(request, profile):
    req = json.loads(request.body.decode())
    #import pdb;pdb.set_trace()
    #player_obj = player.objects.get(user=profile, game_id='2')
    goods_name = req['name']
    try:
        goods = Purchased.objects.get(user=profile, comd_name = goods_name)
    except:
        return '404', '您未购买该商品', 'none'
    if goods.status == '0':
        comds_list = [_.category for _ in Purchased.objects.filter(user=profile, status='1')]
        #using_comd_list = [_.category for _ in Used_comd.objects.filter(user=profile)]
        if goods.category in comds_list:
            comd = Purchased.objects.get(user=profile, category = goods.category, status='1')
            comd.status = '0'
            goods.status = '1'
            goods.save()
            comd.save()
            #if goods.category in using_comd_list:
            Used_comd.objects.get(user=profile, category_id=goods.category).delete()
            using_comd = Used_comd.objects.create(
                comd_name = goods.comd_name+'_game',
                category = goods.category,
                user = profile
            )
            using_comd.save()
            # else:
            #     using_comd = Used_comd.objects.create(
            #         comd_name=goods.comd_name + '_game',
            #         category=goods.category,
            #         user=profile
            #     )
            #     using_comd.save()
            return '200', '更换成功', 'none'
        else:
            goods.status = '1'
            goods.save()
            #if goods.category in using_comd_list:
            #del_using_comd = Used_comd.objects.get(user=profile, category_id=goods.category).delete()
            using_comd = Used_comd.objects.create(
                comd_name = goods.comd_name+'_game',
                category = goods.category,
                user = profile
            )
            using_comd.save()
            return '200', '装备成功', 'none'
    else:
        return '205', '您已装备该道具', 'none'

#游戏过程中获取已装备道具
@check_method('POST')
@login_required
def get_used_comd(request, profile):
    #import pdb;pdb.set_trace()

    req = json.loads(request.body.decode())
    print(req)
    #import pdb;pdb.set_trace()
    # identity_list = req['identity_list']
    # identities = [_ for _ in identity_list]
    #接收用户的identity，没有就传'none'
    identity = req['identity']
    #ip = request.META['REMOTE_ADDR']
    #print(ip)

    id1 = req['identity1']
    id2 = req['identity2']
    id3 = req['identity3']
    id4 = req['identity4']
    id5 = req['identity5']
    id6 = req['identity6']
    id7 = req['identity7']
    num1 = req['player_no1']
    num2 = req['player_no2']
    num3 = req['player_no3']
    num4 = req['player_no4']
    num5 = req['player_no5']
    num6 = req['player_no6']
    num7 = req['player_no7']
    nums = [num1,num2, num3, num4, num5, num6, num7]
    identities = [id1, id2, id3, id4, id5, id6, id7]
    all_info = []
    for id_num in identities:
        if id_num == 'none':
            continue
        else:
            mobile = connect.IdentityRedis.get(id_num)
            current_profile = RealName.objects.get(mobile=mobile)
            local_mobile = connect.IdentityRedis.get(identity)
            local_profile = RealName.objects.get(mobile=local_mobile)
            #print(current_profile.user_id)
            #all_info = []
            #查找所有玩家已经装备的头像
            try:
                avatar_obj = Used_comd.objects.get(user_id=current_profile.user_id, category_id='2')
            except:
                avatar_name = 'none'
            else:
                avatar_name = avatar_obj.comd_name
            #查找所有玩家已装备的头像框
            try:
                frame_obj = Used_comd.objects.get(user_id=current_profile.user_id, category_id='1')
            except:
                frame_name = 'none'
            else:
                frame_name = frame_obj.comd_name
            #查找当前用户已装备的桌面
            try:
                table_obj = Used_comd.objects.get(user_id=local_profile.user_id, category_id='3')
            except:
                table_name = 'none'
            else:
                table_name = table_obj.comd_name
            #查找所有玩家已装备的扑克主题
            try:
                card_obj = Used_comd.objects.get(user_id=current_profile.user_id, category_id='5')
            except:
                card_name = 'none'
            else:
                card_name = card_obj.comd_name
            #判断是否是当前用户
            if id_num == identity:
                is_self = 'true'
            else:
                is_self = 'false'
            id_position = identities.index(id_num)
            print(id_position)
            position = nums[id_position]
            print(position)
            all_comd = {'identity':id_num, 'position':position, 'avatar': avatar_name, 'frame': frame_name, 'card': card_name, 'table': table_name, 'is_self': is_self}
            all_info.append(all_comd)
    return '200', '查询成功', all_info


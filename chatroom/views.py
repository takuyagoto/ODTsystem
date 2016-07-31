# -*- coding: utf-8 -*-
from django.shortcuts import render, HttpResponseRedirect, HttpResponse
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, logout, login
from django.core.cache import cache
from django.core.paginator import PageNotAnInteger, Paginator, EmptyPage
from . import models
import json
import time
from queue import Queue
from django.conf import settings

# Create your views here.

LOGIN_USER_ID = []

GLOBAL_QUEUE = {}


@login_required
def mainindex(request):
    return HttpResponseRedirect(reverse("chat_main", args=[]))


@login_required
def index(request):
    if request.method == "POST":  
        data = request.POST
        print('POST:', data, request.FILES)
        msg_type = request.POST['send_type'].split('|')
        file_content = save_file_for_upload(request.FILES['file'], str(request.user.loginuser.id))
        file_type = msg_type[0]
        to_user = msg_type[1]
        from_user_img = msg_type[2]
        from_user_name = msg_type[3]
        data = {}
        data['from_user'] = request.user.loginuser.id
        data['to_user'] = to_user
        data['msg_type'] = file_type  #
        data['message'] = file_content
        data['send_date'] = time.strftime("%X", time.localtime())
        data['from_user_img'] = from_user_img
        data['send_user_name'] = from_user_name
        analysis_msg(data)
        return HttpResponse("ok")

    friends_list = []
    cache_friends_id = []
    user_groups = request.user.loginuser.mygroup.select_related()
    for group in user_groups:
        members = group.members.select_related()
        for friend in members:
            cache_friends_id.append(friend.id)
        friends_list.append({group: members})

    cache.set('friends_member_' + str(request.user.loginuser.id), cache_friends_id, 86400)#cache.set()
    cache.set('online_stat_' + str(request.user.loginuser.id), 1, 300)

    web_groups = request.user.loginuser.webgroup_member.select_related()
    online_friends = _get_online_friends(request)
    return render(request, 'chatroom/index.html', {'friendlist': friends_list,
                                                   'webgroup_list': web_groups,
                                                   'curr_login_user': online_friends})


def load_all_user(request):
    return_user = []
    search_user = request.GET['condation']
    user_list = models.LoginUser.objects.filter(fullname__contains=search_user)
    paginaobj = Paginator(user_list, 3)  
    page = request.GET.get('page', 1)
    try:
        show_list = paginaobj.page(page)
    except PageNotAnInteger:
        show_list = paginaobj.page(1)
    except EmptyPage:
        show_list = paginaobj.page(paginaobj.num_pages)

    for userobj in show_list:
        return_user.append({'username': userobj.fullname,
                            'userimg': userobj.head_img,
                            'sex': '男性' if userobj.sex == 'F' else '女性',
                            'status': 'online' if cache.get('online_stat_' + str(userobj.id)) else 'offline',
                            'age': userobj.age,
                            'id': userobj.id,
                            'remark': userobj.remark
                            })

    page_html = __build_page(show_list)
    return HttpResponse(json.dumps([return_user, page_html]))


def auth_login(request):
    if request.method == "POST":
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(username=username, password=password)
        if user is not None:
            if user.is_active:
                login(request, user)
                # request.session.set_expiry(1800)
                LOGIN_USER_ID.append(request.user.loginuser.id)
                print(LOGIN_USER_ID)
                return HttpResponseRedirect(reverse('chat_main', args=[]))
        else:
            return render(request, 'login.html', {'errors': u'error login'})
    return render(request, 'login.html')


def auth_logout(request):

    if request.user.loginuser.id in LOGIN_USER_ID:
        LOGIN_USER_ID.remove(request.user.loginuser.id)
    cache.delete('online_stat_' + str(request.user.loginuser.id))
    logout(request)
    request.session.clear_expired()
    return HttpResponseRedirect(reverse('login', args=[]))


def send_msg(request):
    if request.method == "POST":
        post_data = request.POST['data']
        data = json.loads(post_data)
        data['from_user'] = request.user.loginuser.id
        data['send_date'] = time.strftime("%X", time.localtime()) 
        # print(data)
        analysis_msg(data)
        return HttpResponse("OK")


def analysis_msg(data):
    type_and_id = data['to_user'].split("_")
    send_to_type = type_and_id[0]
    send_to_id = type_and_id[1]
    if send_to_type == "user":
        store_msg(int(send_to_id), data)
    else:
        # print('send msg to group')
        group_id = int(send_to_id)
        user_list = models.WebGroups.objects.get(id=group_id).members.select_related().values('id')
        # print('userlist:', user_list)
        for user in user_list:
            user_id = int(user['id'])
            if user_id != data['from_user']: 
                store_msg(user_id, data)


def store_msg(userid, data):
    # print(userid, GLOBAL_QUEUE)
    if not userid in GLOBAL_QUEUE.keys(): 
        # print("user %s not in queue dice" % str(userid))
        new_queue = Queue()
        new_queue.put(data)
        GLOBAL_QUEUE[userid] = new_queue
    else:
        # print("has key, store data")
        user_queue = GLOBAL_QUEUE.get(userid)
        user_queue.put(data)
        # print(GLOBAL_QUEUE)


def get_msg(request):
    print("comes a request")
    queue_message = []
    user_id = int(request.user.loginuser.id)
    # print("get message by :", user_id)
    if user_id in GLOBAL_QUEUE.keys():
        # print("find message queue to user:", user_id)
        user_queue = GLOBAL_QUEUE[user_id]
        while not user_queue.empty():
            # print("has messages....")
            queue_message.append(user_queue.get())
    else:
        GLOBAL_QUEUE[user_id] = Queue()
        # print("no this users queue, create a new one....")

    if len(queue_message) == 0:
        try:
            print('no message for you, waitting.......')
            queue_message.append(GLOBAL_QUEUE[user_id].get(timeout=60))
        except ConnectionAbortedError:
            print('aborted to many....')
            return HttpResponse('error')
        except Exception as e:
            print('waitting for message, Time Out for 60 sec')
    # print("return data...........")
    return HttpResponse(json.dumps(queue_message))


def updata_status(request):

    request_user_id = request.user.loginuser.id
    cache.set('online_stat_' + str(request_user_id), 1, 300)
    online_friends = _get_online_friends(request)

    return HttpResponse(json.dumps(online_friends))


def _get_online_friends(request):
    online_friends = []
    request_user_id = request.user.loginuser.id
    friends_id = cache.get('friends_member_' + str(request_user_id))
    if not friends_id:
        tmplist = []
        my_friends_idlist = request.user.loginuser.friends.values('id')
        for result in my_friends_idlist:
            tmplist.append(result['id'])
        cache.set('friends_member_' + str(request_user_id), tmplist, 86400)
        friends_id = cache.get('friends_member_' + str(request_user_id))

    for id in friends_id:
        if cache.get('online_stat_' + str(id)):
            online_friends.append(id)
    return online_friends


def save_file_for_upload(fileobj, userid):
    print('begin recv data:.......')
    save_file_path = settings.BASE_DIR + "/statics/uploads/"
    file_name = userid + "_" + fileobj.name
    print(file_name)
    recv_size = 0
    with open(save_file_path + file_name, 'wb+') as f:
        for trunc in fileobj.chunks(1024):
            f.write(trunc)
            recv_size += len(trunc)
            # print('recved file size:', recv_size)
            cache.set(file_name, recv_size)
        cache.set(file_name, recv_size, 5)

    return '/static/uploads/' + file_name


def get_upload_size(request):
    file_name = request.GET['file_name']
    recv_size = cache.get(file_name)
    # print('send_recv_size:', recv_size)
    return HttpResponse(recv_size)


def __build_page(result_obj):
    return_str = "<nav>"
    return_str += "<ul class='pagination  pull-right'>"
    if result_obj.has_previous():
        return_str += "<li>"
        return_str += "<a href='#' onclick='addFriends(" + str(
            result_obj.previous_page_number()) + ");' aria-label='Previous'>"
        return_str += "<span aria-hidden='true'>&laquo;</span>"
        return_str += "</a></li>"

    for i in result_obj.paginator.page_range:
        # print(i,result_obj.paginator.page_range,result_obj.number)
        hide_page_num = abs(result_obj.number - i)
        if hide_page_num <= 2:
            return_str += "<li "
            if i == result_obj.number:
                return_str += "class='active'><a href='#' onclick='addFriends(" + str(i) + ");'>" + str(i) + "</a></li>"
            else:
                return_str += "><a href='#' onclick='addFriends(" + str(i) + ");'>" + str(i) + "</a></li>"

    if result_obj.has_next():
        return_str += "<li><a href='#' onclick='addFriends(" + str(
            result_obj.next_page_number()) + ");' aria-label='Next'>"
        return_str += "<span aria-hidden='true'>&raquo;</span></a></li></ul></nav>"

    return return_str


def add_friend(request):
    if request.method == "POST":
        group_id = request.POST['group_id']
        user_id = request.POST['user_id']
        friends_id_list = request.user.loginuser.friends.select_related().values('id')
        for friend in friends_id_list:
            if int(user_id) == friend['id']:
                print('friends exists...')
                return HttpResponse("1")
            else:
                models.UserGroup.objects.get(id=int(group_id)).members.add(models.LoginUser.objects.get(id=int(user_id)))
                request.user.loginuser.friends.add(models.LoginUser.objects.get(id=int(user_id)))
                models.UserGroup.objects.get(owner_id=int(user_id), isdefault=1).members.add(
                models.LoginUser.objects.get(id=int(request.user.loginuser.id)))
                return HttpResponse("0")


def load_group_members(request):
    group_id = request.GET['groupid']
    members_obj_list = models.WebGroups.objects.get(id=int(group_id)).members.select_related().values('fullname','head_img')
    print(type(list(members_obj_list)))
    return HttpResponse(json.dumps(list(members_obj_list)))



Cần bổ sung một số rule mới cho các vấn đề tôi đang gặp. hãy nghiên cứu và xem tính thực thi. 
1. Check lại xem hiện nay khi regen có restart lại CDP ko (tôi để ý khi regen đều kill brave đang chạy dù nó đang chạy tốt) gây khó chịu 
2. check lại cơ chế bộ ba nút Image - Video - Voice hiện nay. Hiện nay Image ko ấn được nếu ko có Image đã gen. về cơ bản là đúng rule ban đầu. nhưng có thể chuyển cơ chế các nút này thành: 
Ko cần image hay vid gen trước. nếu chưa có để black. vì hiện nay video cũng ko xem đc, có thể do thiêu codec. 
Thay nút Re-Gen bằng nút Gen. chuyển chúng thành cơ chế Gen lẻ. Lúc này phải hiện prompt cho image và vid ở đó để User có thể sửa và Gen. Khi ấn Gen thì quá trình : ghi trạng thái mới vào scenes_edited.json và bắt đầu gen. Video thực tế có thể gen ko cần prompt. Nên điều chỉnh nhưu vậy là tiện nhất. 
3. Nút Edit all hiện tại : đang chỉ có regen cho image. (kiểm tra lại) . Nếu đúng thì bổ sung Save (lưu lại trạng thái ở edited json) gen image và gen video (bỏ tên regen đi vì ko cần thiết) 
4. kiem tra lại logic khi toi load file ví dụ ABC.json là file project thì tôi cần file abc_edited.json là file lưu thay đổi và abc_state.json là file lưu log. logic này hiện nay chưa có đúng ko. 
5. Khi load file project hiện nay, ví dụ tôi load file abc.json thì dự án load luôn file abc_edited.json trong cùng thư mục để hiện ra trạng thái mới nhất đúng ko. 
6. Đối với slideshow animation. Nếu mở video_screen ra, thì bất kể prompt gì, nếu tôi để state là slide_show và chọn Gen thì sẽ thực hiện function này 